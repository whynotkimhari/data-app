import os
import json
import pandas as pd
import streamlit as st
import base64
from PIL import Image
import io
import re
import boto3
from botocore.config import Config
import streamlit.components.v1 as components
from datetime import datetime


# ---------- CONFIG ----------
PREVIEWS_DIR = "./results/all_previews"
METADATA_FILE = "./results/perturbed_labels.json"

def get_r2_config():
    """Safely get R2 config from secrets (root or [R2] section)"""
    try:
        if "ENDPOINT" in st.secrets and "ACCESS_KEY" in st.secrets:
            return {
                "ENDPOINT": st.secrets["ENDPOINT"],
                "ACCESS_KEY": st.secrets["ACCESS_KEY"],
                "SECRET_KEY": st.secrets["SECRET_KEY"],
                "BUCKET": st.secrets.get("BUCKET", "dataapp")
            }
    except Exception:
        pass
    return {}

R2_CONFIG = get_r2_config()

def get_s3_client():
    if R2_CONFIG.get("ENDPOINT"):
        return boto3.client(
            "s3",
            endpoint_url=R2_CONFIG["ENDPOINT"],
            aws_access_key_id=R2_CONFIG["ACCESS_KEY"],
            aws_secret_access_key=R2_CONFIG["SECRET_KEY"],
            config=Config(signature_version="s3v4"),
            region_name="auto"
        )
    return None

S3_CLIENT = get_s3_client()
BUCKET_NAME = R2_CONFIG.get("BUCKET", "dataapp")
# Check if we should actually use cloud mode (only if R2_CONFIG has data)
# Note: For now, we prefer cloud if credentials exist.
STORAGE_MODE = "cloud" if S3_CLIENT else "local"

st.set_page_config(layout="wide", page_title="MRI Review Pro")

# ---------- STYLING ----------
st.markdown("""
<style>
    .stMainBlockContainer {
        padding-top: 3rem !important;
        padding-bottom: 2rem !important;
        max-width: 95% !important;
    }
    .stButton > button {
        width: 100%;
        height: 3em;
        font-weight: bold;
    }
    .status-box {
        padding: 5px;
        border-radius: 5px;
        text-align: center;
        margin-bottom: 10px;
        font-weight: bold;
        height: 35px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .status-pending { background-color: #f0f2f6; color: #31333f; }
    .status-approved { background-color: #d4edda; color: #155724; }
    .status-rejected { background-color: #f8d7da; color: #721c24; }
    .image-container {
        border-radius: 4px;
        padding: 0px;
        margin-top: 20px;
        display: flex;
        justify-content: center;
        background-color: #0e1117;
    }
    .info-line {
        font-size: 0.9rem;
        color: #888;
        text-align: center;
        margin-top: 10px;
        margin-bottom: 5px;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ---------- DATA LOADING ----------
@st.cache_data
def load_all_data():
    """Returns (previews_map, metadata_lookup, gold_lookup)
    previews_map: {patient_id: [slides...]}
    metadata_lookup: {(pid, slide): origin_slice}
    gold_lookup: {pid: origin_slice}
    """
    if not os.path.exists(METADATA_FILE):
        return {}, {}, {}
        
    with open(METADATA_FILE, 'r') as f:
        data = json.load(f)
    
    previews = {}
    meta = {}
    gold = {}
    
    for item in data:
        pid = item['patient_id']
        slide = item['slide']
        origin = item['origin_slice']
        
        # Build previews_map
        if pid not in previews:
            previews[pid] = []
        if slide not in previews[pid]:
            previews[pid].append(slide)
            
        # Build lookups
        meta[(pid, slide)] = origin
        if pid not in gold:
            gold[pid] = origin
            
    # Sort for consistency
    for pid in previews:
        previews[pid].sort()
        
    return previews, meta, gold

# ---------- STORAGE HELPERS ----------
def sanitize_id(raw_id):
    """Keep only alphanumeric, underscores, and hyphens"""
    if not raw_id: return ""
    return re.sub(r'[^a-zA-Z0-9_\-]', '', raw_id)

def load_decisions(doctor_id):
    """Note: Automatic loading from disk is disabled to avoid path errors."""
    return {}

@st.cache_data(show_spinner=False)
def get_image_data_base64(patient_id, current_file):
    """Fetches image from Cloud (R2) or Local disk and returns base64 string"""
    if STORAGE_MODE == "cloud":
        try:
            # Objects are at root, e.g. "OAS1_0001/mpr-1_100.jpg"
            key = f"{patient_id}/{current_file}"
            response = S3_CLIENT.get_object(Bucket=BUCKET_NAME, Key=key)
            data = response["Body"].read()
            return base64.b64encode(data).decode()
        except Exception as e:
            st.error(f"Cloud fetch error: {e} | Bucket: {BUCKET_NAME} | Key: {key}")
            return None
    else:
        # Local fallback
        img_path = os.path.join(PREVIEWS_DIR, patient_id, current_file)
        if os.path.exists(img_path):
            with open(img_path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            return data
        return None

# metadata_lookup, gold_lookup, and previews_map are now all derived from metadata

# ---------- SESSION STATE ----------
def init_state(doctor_id):
    if "decisions" not in st.session_state or st.session_state.get("last_doctor") != doctor_id:
        st.session_state["decisions"] = load_decisions(doctor_id)
        st.session_state["last_doctor"] = doctor_id
    if "idx" not in st.session_state:
        st.session_state["idx"] = 0
    if "last_patient" not in st.session_state:
        st.session_state["last_patient"] = None

# ---------- SIDEBAR - USER AUTH ----------
st.sidebar.title("👨‍⚕️ Doctor Login")

# Use session state to handle login "locking"
if "authenticated_doctor" not in st.session_state:
    st.session_state["authenticated_doctor"] = None

if not st.session_state["authenticated_doctor"]:
    raw_id = st.sidebar.text_input("Enter your Name or ID", placeholder="e.g. Dr. Smith").strip()
    if raw_id:
        clean_id = sanitize_id(raw_id)
        if clean_id:
            if st.sidebar.button("Login"):
                st.session_state["authenticated_doctor"] = clean_id
                st.rerun()
        else:
            st.sidebar.error("⚠️ ID contains invalid characters. Use alphanumeric, _ or -")
    
    st.info("👋 Welcome! Please login in the sidebar to start reviewing.")
    st.stop()
else:
    doctor_id = st.session_state["authenticated_doctor"]
    st.sidebar.success(f"Logged in: **{doctor_id}**")
    if st.sidebar.button("🔓 Change Doctor / Logout", icon="🔄"):
        st.session_state["authenticated_doctor"] = None
        st.rerun()

# Initialize state with doctor context
init_state(doctor_id)

previews_map, metadata_lookup, gold_lookup = load_all_data()

if not previews_map:
    st.error(f"Metadata file not found or empty at {METADATA_FILE}. Please ensure it is present in the repository.")
    st.stop()

patients = sorted(list(previews_map.keys()))

# ---------- NAVIGATION HELPERS ----------
def go_next(max_idx, doctor_id):
    init_state(doctor_id)
    if st.session_state["idx"] < max_idx:
        st.session_state["idx"] += 1

def go_prev(doctor_id):
    init_state(doctor_id)
    if st.session_state["idx"] > 0:
        st.session_state["idx"] -= 1

def set_decision(status, file_key, max_idx, doctor_id, p_id, orig_s, curr_s):
    init_state(doctor_id)
    st.session_state["decisions"][file_key] = status

# ---------- SIDEBAR ----------
st.sidebar.title("MRI Review Pro")

selected_patient = st.sidebar.selectbox("Select Patient", patients)

# Reset index if patient changed
if st.session_state["last_patient"] != selected_patient:
    st.session_state["idx"] = 0
    st.session_state["last_patient"] = selected_patient

patient_files = previews_map[selected_patient]
max_idx = len(patient_files) - 1
idx = st.session_state["idx"]
current_file = patient_files[idx]
file_key = f"{selected_patient}/{current_file}"

# Progress
total_patient_files = len(patient_files)
decisions_count = sum(1 for f in patient_files if f"{selected_patient}/{f}" in st.session_state["decisions"])
st.sidebar.progress(decisions_count / total_patient_files)
st.sidebar.write(f"Patient Progress: {decisions_count}/{total_patient_files}")

# Help & Shortcuts
with st.sidebar.expander("⌨️ Help & Shortcuts"):
    st.markdown("""
    - **A**: Approve
    - **R**: Reject
    - **C**: Reset Decision
    - **Left Arrow**: Previous
    - **Right Arrow**: Next
    
    *Decisions are saved automatically for your session.*
    """)

# ---------- MAIN UI ----------

# 1. Status Display at the very top
status = st.session_state["decisions"].get(file_key, "Pending")
status_class = "status-" + status.lower()
st.markdown(f'<div class="status-box {status_class}">Current Status: {status}</div>', unsafe_allow_html=True)

# 2. All buttons in a single row
slide_name = current_file.replace('.jpg', '')
# A slide is gold if it is the 'origin_slice' for this patient
current_orig_slide = gold_lookup.get(selected_patient, "Unknown")
# Disable if it's the gold slide itself OR if no gold slide exists for this patient
is_readonly = (slide_name == current_orig_slide) or (current_orig_slide in ["none", "Unknown", None])

c_prev, c_app, c_rej, c_clr, c_next = st.columns([1, 1.5, 1.5, 1, 1])
with c_prev:
    st.button("⬅ Prev [Left]", on_click=go_prev, args=(doctor_id,))
with c_app:
    st.button("✅ Approve [A]", 
              on_click=set_decision, 
              args=("Approved", file_key, max_idx, doctor_id, selected_patient, current_orig_slide, slide_name), 
              type="primary", disabled=is_readonly)
with c_rej:
    st.button("❌ Reject [R]", 
              on_click=set_decision, 
              args=("Rejected", file_key, max_idx, doctor_id, selected_patient, current_orig_slide, slide_name), 
              disabled=is_readonly)
with c_clr:
    if st.button("🔄 Reset [C]", disabled=is_readonly):
        if file_key in st.session_state["decisions"]:
            del st.session_state["decisions"][file_key]
        st.rerun()
with c_next:
    st.button("Next [Right] ➡", on_click=go_next, args=(max_idx, doctor_id))

# 3. Information Line below buttons
st.markdown(f'<div class="info-line">Patient: <b>{selected_patient}</b> | Slide: <b>{current_file}</b> | Index: <b>{idx+1}/{total_patient_files}</b></div>', unsafe_allow_html=True)

# Current Image
img_data = get_image_data_base64(selected_patient, current_file)
if img_data:
    st.markdown(f'''
        <div class="image-container" data-is-readonly="{"true" if is_readonly else "false"}">
            <img src="data:image/jpeg;base64,{img_data}" style="max-height: 75vh; width: auto; max-width: 100%;">
        </div>
    ''', unsafe_allow_html=True)
else:
    st.error(f"Image not found: {selected_patient}/{current_file} (Mode: {STORAGE_MODE})")

# Import / Export
st.sidebar.markdown("---")
st.sidebar.subheader("💾 Session Management")

# Use a key based on session state to allow clearing the uploader
if "uploader_key" not in st.session_state:
    st.session_state["uploader_key"] = 1

# Import
uploaded_file = st.sidebar.file_uploader("📤 Import Session (JSON)", type=["json"], key=f"uploader_{st.session_state['uploader_key']}")
if uploaded_file is not None:
    try:
        imported_decisions = json.load(uploaded_file)
        if isinstance(imported_decisions, dict):
            if st.sidebar.button("Confirm Import & Override"):
                st.session_state["decisions"] = imported_decisions
                
                # Increment key to clear uploader
                st.session_state["uploader_key"] += 1
                st.sidebar.success("Session imported successfully!")
                st.rerun()
        else:
            st.sidebar.error("Invalid session file format.")
    except Exception as e:
        st.sidebar.error(f"Import failed: {e}")

# Export JSON (For importing later)
json_data = json.dumps(st.session_state["decisions"], indent=4)
st.sidebar.download_button(
    label="📥 Export Session (JSON)",
    data=json_data,
    file_name=f"decisions_{doctor_id}.json",
    mime="application/json",
    help="Download your raw decisions to restore later using 'Import Session'."
)

# Export CSV (Final results)
# Generate CSV data immediately for the download button
data_list = []
for key, val in st.session_state["decisions"].items():
    try:
        p_id, f_name = key.split('/')
        sn = f_name.replace('.jpg', '')
        orig_s = metadata_lookup.get((p_id, sn), "Unknown")
        data_list.append({
            "doctor_id": doctor_id,
            "patient_id": p_id,
            "original_slide": orig_s,
            "current_slide": sn,
            "is_accepted": 1 if val == "Approved" else 0,
            "decision": val
        })
    except: continue

if data_list:
    df_export = pd.DataFrame(data_list)
    csv_data = df_export.to_csv(index=False)
    st.sidebar.download_button(
        label="📊 Export Final Results (CSV)",
        data=csv_data,
        file_name=f"review_results_{doctor_id}.csv",
        mime="text/csv"
    )
else:
    st.sidebar.write("*(No decisions to export yet)*")

# Keyboard Shortcuts
components.html(
    """
    <script>
    const doc = window.parent.document;
    doc.addEventListener('keydown', function(e) {{
        // Ignore if typing in an input
        if (e.target.tagName.toLowerCase() === 'input' || e.target.tagName.toLowerCase() === 'textarea') return;
        
        const container = doc.querySelector('[data-is-readonly]');
        const isReadOnly = container && container.getAttribute('data-is-readonly') === 'true';
        
        const key = e.key.toLowerCase();
        const buttons = Array.from(doc.querySelectorAll('button'));
        
        // Handle shortcuts
        if (e.keyCode === 37) {{ // Left
            const b = buttons.find(x => x.innerText.includes('Prev'));
            if (b) b.click();
        }} else if (e.keyCode === 39) {{ // Right
            const b = buttons.find(x => x.innerText.includes('Next'));
            if (b) b.click();
        }} else if (key === 'a' && !isReadOnly) {{ // A for Approve
            const b = buttons.find(x => x.innerText.includes('Approve'));
            if (b) b.click();
        }} else if (key === 'r' && !isReadOnly) {{ // R for Reject
            const b = buttons.find(x => x.innerText.includes('Reject'));
            if (b) b.click();
        }} else if (key === 'c') {{ // C for Reset
            // IMPORTANT: ALWAYS Stop Streamlit from seeing this 'C' (it opens the scary cache menu)
            e.preventDefault();
            e.stopPropagation();
            
            if (!isReadOnly) {{
                const b = buttons.find(x => x.innerText.includes('Reset'));
                if (b) b.click();
            }}
        }}
    }}, true);
    </script>
    """,
    height=0,
)
