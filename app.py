import os
import ast
import json
import re
import io
import base64
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw

# ---------- SETTINGS ----------
BASE_DATA_FOLDER = "./Data_by_Patient"  # Status/PatientID/images
EXCEL_PATH = "./AI in Dementia Diagnosis Project_Final.xlsx"
LABELS_PATH = "./results/accepted_labels.json"
PROPAGATION_MAX_DIST = 5  # Max slides to project bounding boxes

st.set_page_config(layout="wide")
st.title("MRI Bounding Box Review")

@st.cache_data
def load_gold_standard(excel_path):
    df = pd.read_excel(excel_path)
    
    def parse_bbox(val):
        if pd.isna(val) or str(val).strip() == '': return []
        try:
            val_str = str(val).strip()
            if not val_str.startswith('['): val_str = f'[{val_str}]'
            parsed = ast.literal_eval(f'[{val_str}]')
            
            flat_boxes = []
            def search_boxes(lst):
                if isinstance(lst, list) and len(lst) == 4 and all(isinstance(x, (int, float)) for x in lst):
                    flat_boxes.append(lst)
                elif isinstance(lst, list):
                    for item in lst:
                        search_boxes(item)
            
            search_boxes(parsed)
            return flat_boxes
        except:
            return []

    gold_dict = {}
    for _, row in df.iterrows():
        pid = row.get('Patient ID')
        slide = row.get('Slide')
        boxes_raw = row.get('Corrected and rotated BBOX [x1, y1, x2, y2]')
        notes_raw = row.get('Notes')
        if pd.isna(pid) or pd.isna(slide): continue
        
        boxes = parse_bbox(boxes_raw)
        if not boxes: continue
        
        notes = str(notes_raw) if pd.notna(notes_raw) else ""
        filename = f"{pid}_MR1_{slide}.jpg"
        gold_dict[filename] = {"boxes": boxes, "notes": notes}
        
    return gold_dict

@st.cache_data
def build_status_map(base_folder):
    """Scan Base/Status/PatientID/ to build filename -> dementia status mapping."""
    status_map = {}
    if not os.path.exists(base_folder):
        return status_map
    for status_folder in os.listdir(base_folder):
        status_path = os.path.join(base_folder, status_folder)
        if not os.path.isdir(status_path) or status_folder.startswith('.'):
            continue
        for patient_folder in os.listdir(status_path):
            patient_path = os.path.join(status_path, patient_folder)
            if not os.path.isdir(patient_path) or patient_folder.startswith('.'):
                continue
            for img_file in os.listdir(patient_path):
                if not img_file.startswith('.'):
                    status_map[img_file] = status_folder
    return status_map

@st.cache_data
def build_patient_status_map(base_folder):
    """Build patient_id -> (status_folder, full_path) mapping."""
    patient_map = {}
    if not os.path.exists(base_folder):
        return patient_map
    for status_folder in sorted(os.listdir(base_folder)):
        status_path = os.path.join(base_folder, status_folder)
        if not os.path.isdir(status_path) or status_folder.startswith('.'):
            continue
        for patient_folder in sorted(os.listdir(status_path)):
            patient_path = os.path.join(status_path, patient_folder)
            if not os.path.isdir(patient_path) or patient_folder.startswith('.'):
                continue
            patient_map[patient_folder] = {
                "status": status_folder,
                "path": patient_path,
            }
    return patient_map

def parse_filename(filename):
    """Extract Patient ID and Slide from filename like OAS1_0001_MR1_mpr-1_106.jpg"""
    parts = filename.replace('.jpg', '').split('_MR1_')
    patient_id = parts[0] if len(parts) > 0 else ""
    slide = parts[1] if len(parts) > 1 else ""
    return patient_id, slide

def load_accepted_labels(json_path):
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_accepted_labels(json_path, labels):
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, 'w') as f:
        json.dump(labels, f, indent=4)

status_map = build_status_map(BASE_DATA_FOLDER)
patient_status_map = build_patient_status_map(BASE_DATA_FOLDER)
gold_labels = load_gold_standard(EXCEL_PATH)
if "accepted_labels" not in st.session_state:
    st.session_state["accepted_labels"] = load_accepted_labels(LABELS_PATH)
accepted_labels = st.session_state["accepted_labels"]

if not os.path.exists(BASE_DATA_FOLDER):
    st.error(f"Base data folder not found: {BASE_DATA_FOLDER}")
    st.stop()

gold_patient_ids = set([filename.split('_MR1_')[0] for filename in gold_labels.keys()])

# Filter patients that exist in both folder structure and gold standard
patients = sorted([pid for pid in patient_status_map.keys() if pid in gold_patient_ids])

if not patients:
    st.error("No patient folders found that match the Gold Standard Excel file!")
    st.stop()

st.sidebar.header("Settings")
selected_patient = st.sidebar.selectbox("Select Patient", patients,
    format_func=lambda p: f"{p} ({patient_status_map[p]['status']})")
IMAGE_FOLDER = patient_status_map[selected_patient]["path"]

if "current_patient" not in st.session_state or st.session_state["current_patient"] != selected_patient:
    st.session_state["idx"] = 0
    st.session_state["current_patient"] = selected_patient

files = sorted([f for f in os.listdir(IMAGE_FOLDER)
                if f.endswith((".png", ".jpg", ".jpeg")) and not f.startswith('.')])
if not files:
    st.error(f"No images found for patient {selected_patient}!")
    st.stop()

idx = st.session_state.get("idx", 0)
current_file = files[idx]

# -----------------
# Determine nearest box and its status
# -----------------
@st.cache_data
def get_slice_info(filename):
    match = re.search(r'(mpr-\d+)_(\d+)\.jpg', filename)
    if match:
        return match.group(1), int(match.group(2))
    return None, None

@st.cache_data
def precompute_slice_info(files_list):
    res = {}
    for f in files_list:
        mpr, num = get_slice_info(f)
        if mpr:
            res[f] = (mpr, num)
    return res

def find_nearest_boxes(files_list, current_f, max_dist=5):
    cur_mpr, cur_num = get_slice_info(current_f)
    if not cur_mpr: return None, 0, None, ""
    
    best_dist = max_dist + 1
    best_boxes = None
    best_f = None
    best_notes = ""
    
    slice_info_map = precompute_slice_info(tuple(files_list))
    
    for f in files_list:
        if f == current_f: continue
        if f not in slice_info_map: continue
        
        mpr, num = slice_info_map[f]
        dist = abs(num - cur_num)
        if dist < best_dist:
            if f in gold_labels:
                best_dist = dist
                best_boxes = gold_labels[f]["boxes"]
                best_notes = gold_labels[f]["notes"]
                best_f = f
            elif f in accepted_labels:
                # handle legacy array format or new dict format
                labels_data = accepted_labels[f]
                if isinstance(labels_data, dict) and "boxes" in labels_data:
                    best_boxes = labels_data["boxes"]
                    best_notes = labels_data.get("notes", "")
                    best_f = labels_data.get("origin_slice") or f
                else:
                    best_boxes = labels_data
                    best_notes = ""
                    best_f = f
                best_dist = dist
                    
    if best_dist <= max_dist:
        return best_boxes, best_dist, best_f, best_notes
    return None, 0, None, ""

# logic to determine current boxes
boxes_to_draw = []
box_color = "red" # red=gold, green=accepted, yellow=propagated
box_status = "None"
origin_file = None
current_notes = ""

if current_file in accepted_labels:
    labels_data = accepted_labels[current_file]
    if isinstance(labels_data, dict) and "boxes" in labels_data:
        boxes_to_draw = labels_data["boxes"]
        current_notes = labels_data.get("notes", "")
    else:
        boxes_to_draw = labels_data # fallback for legacy json
    box_color = "lime"
    box_status = "Accepted"
elif current_file in gold_labels:
    boxes_to_draw = gold_labels[current_file]["boxes"]
    current_notes = gold_labels[current_file]["notes"]
    box_color = "red"
    box_status = "Gold Standard"
else:
    best_boxes, dist, best_f, best_notes = find_nearest_boxes(files, current_file, PROPAGATION_MAX_DIST)
    if best_boxes:
        boxes_to_draw = best_boxes
        current_notes = best_notes
        box_color = "yellow"
        origin_file = best_f
        box_status = f"Propagated (Nearest Dist: {dist})"

def _build_label_entry(filename, origin_slice, boxes, notes):
    """Build a structured label entry with Patient ID, Slide, Status."""
    patient_id, slide = parse_filename(filename)
    return {
        "patient_id": patient_id,
        "slide": slide,
        "status": status_map.get(filename, "Unknown"),
        "origin_slice": origin_slice,
        "boxes": boxes,
        "notes": notes,
    }

def update_notes_cb():
    note_val = st.session_state["notes_input"]
    # Only update notes for already-accepted entries, never create new ones
    if current_file not in st.session_state["accepted_labels"]:
        return
    l_data = st.session_state["accepted_labels"][current_file]
    if isinstance(l_data, dict):
        l_data["notes"] = note_val
    else:
        st.session_state["accepted_labels"][current_file] = _build_label_entry(
            current_file, None, l_data, note_val
        )
    save_accepted_labels(LABELS_PATH, st.session_state["accepted_labels"])

col_status, col_accept = st.columns([3, 1])

def toggle_accept_current_cb(curr_file, status, bboxes, origin_f, notes):
    if curr_file in st.session_state["accepted_labels"]:
        del st.session_state["accepted_labels"][curr_file]
    elif status.startswith("Propagated"):
        st.session_state["accepted_labels"][curr_file] = _build_label_entry(
            curr_file, origin_f, bboxes, notes
        )
    save_accepted_labels(LABELS_PATH, st.session_state["accepted_labels"])

with col_status:
    if box_status == "Gold Standard":
        st.error(f"**Status:** {box_status} 🔴")
    elif box_status == "Accepted":
        st.success(f"**Status:** {box_status} 🟢")
    elif box_status.startswith("Propagated"):
        st.warning(f"**Status:** {box_status} 🟡")
    else:
        st.info("**Status:** No box data ⚪")

with col_accept:
    if box_status == "Accepted":
        st.button("Unaccept [SPACE]", key="btn_toggle", type="secondary", on_click=toggle_accept_current_cb, args=(current_file, box_status, boxes_to_draw, origin_file, current_notes))
    elif box_status.startswith("Propagated"):
        st.button("Accept Box [SPACE]", key="btn_toggle", type="primary", on_click=toggle_accept_current_cb, args=(current_file, box_status, boxes_to_draw, origin_file, current_notes))

st.sidebar.markdown("---")
col1, col2 = st.sidebar.columns(2)

def go_prev():
    st.session_state["idx"] = max(0, st.session_state.get("idx", 0) - 1)
def go_next(max_idx):
    st.session_state["idx"] = min(max_idx, st.session_state.get("idx", 0) + 1)
def toggle_boxes():
    st.session_state["show_boxes"] = not st.session_state.get("show_boxes", True)

if "show_boxes" not in st.session_state:
    st.session_state["show_boxes"] = True

col1.button("⬅ Prev", key="btn_prev", on_click=go_prev)
col2.button("Next ➡", key="btn_next", on_click=go_next, args=(len(files)-1,))
st.sidebar.button("Toggle Boxes [TAB]", key="btn_toggle_boxes", width='stretch', on_click=toggle_boxes)

# load & draw bounding box
def load_image(path):
    img = Image.open(path).convert("RGB")
    if img.width > img.height:
        img = img.transpose(Image.ROTATE_90)
    return img

img_path = os.path.join(IMAGE_FOLDER, current_file)
img = load_image(img_path).copy()
img_w, img_h = img.size

draw = ImageDraw.Draw(img)

if st.session_state["show_boxes"]:
    for box in boxes_to_draw:
        if len(box) == 4:
            # box coords are relative in excel (x1, y1, x2, y2)
            # They are now pre-normalized to the vertical target orientation
            x1_rel, y1_rel, x2_rel, y2_rel = box
            
            x1, y1 = x1_rel * img_w, y1_rel * img_h
            x2, y2 = x2_rel * img_w, y2_rel * img_h
            draw.rectangle([x1, y1, x2, y2], outline=box_color, width=1)

# show
st.caption(f"**Filename:** `{current_file}`")
st.write(f"Slide: {idx+1} / {len(files)}")
# Sync the stable widget key to current slide's notes
st.session_state["notes_input"] = current_notes
is_gold = box_status == "Gold Standard"
st.text_area("Doctor's Notes:", value=current_notes, key="notes_input", on_change=update_notes_cb, disabled=is_gold)



col1, col2, col3 = st.columns([1, 0.5, 1]) # Make center column even smaller (33% width)
with col2:
    # Convert manually to base64 HTML to bypass Streamlit's internal PIL caching leaks
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64_str = base64.b64encode(buf.getvalue()).decode()
    st.markdown(f'<img src="data:image/jpeg;base64,{b64_str}" style="width: 100%;">', unsafe_allow_html=True)

# ----- Keyboard Navigation Injection -----
components.html(
    """
    <script>
    const doc = window.parent.document;
    doc.addEventListener('keydown', function(e) {
        // Prevent default scrolling when using arrows, space, or tab
        if([9, 32, 37, 39].indexOf(e.keyCode) > -1) {
            if(e.target.tagName.toLowerCase() !== 'input' && e.target.tagName.toLowerCase() !== 'textarea') {
                e.preventDefault();
            }
        }
        if (e.keyCode === 9) { // Tab
            const buttons = doc.querySelectorAll('button');
            buttons.forEach(b => {
                if (b.innerText.includes('Toggle Boxes')) { b.click(); }
            });
        }
        if (e.keyCode === 37) { // Left arrow
            const buttons = doc.querySelectorAll('button');
            buttons.forEach(b => {
                if (b.innerText.includes('Prev')) { b.click(); }
            });
        }
        if (e.keyCode === 39) { // Right arrow
            const buttons = doc.querySelectorAll('button');
            buttons.forEach(b => {
                if (b.innerText.includes('Next')) { b.click(); }
            });
        }
        if (e.keyCode === 32) { // Space
            const buttons = doc.querySelectorAll('button');
            buttons.forEach(b => {
                const text = b.innerText;
                if (text.includes('Accept Box') || text.includes('Unaccept')) { b.click(); }
            });
        }
    });
    </script>
    """,
    height=0,
    width=0,
)
