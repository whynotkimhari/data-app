import os
import shutil
from pathlib import Path

def redistribute_images(src_dir: str, dest_dir: str, copy_files: bool = True):
    """
    Redistributes images by status first, then by patient ID.
    Source structure: Data/{Status}/{images}
    Output structure: dest/{Status}/{PatientID}/{images}
    """
    src_path = Path(src_dir)
    dest_path = Path(dest_dir)
    
    if not src_path.exists():
        print(f"Error: Source directory '{src_dir}' does not exist.")
        return

    dest_path.mkdir(parents=True, exist_ok=True)
    processed_count = 0
    
    STATUS_LABELS = {
        "Non Demented": "Non-Dementia",
        "Mild Dementia": "Mild-Dementia",
        "Moderate Dementia": "Moderate-Dementia",
        "Very mild Dementia": "Very-Mild-Dementia",
    }
    
    for status_dir in sorted(src_path.iterdir()):
        if not status_dir.is_dir() or status_dir.name.startswith('.'):
            continue
        
        status_name = STATUS_LABELS.get(status_dir.name, status_dir.name)
        
        for file_path in sorted(status_dir.iterdir()):
            if not file_path.is_file() or file_path.name.startswith('.'):
                continue
            
            filename = file_path.name
            if len(filename) < 9:
                continue
                
            patient_id = filename[:9]
            
            # Status / PatientID / image.jpg
            patient_dir = dest_path / status_name / patient_id
            patient_dir.mkdir(parents=True, exist_ok=True)
            
            dest_file_path = patient_dir / filename
            
            try:
                if copy_files:
                    if not dest_file_path.exists():
                        shutil.copy2(file_path, dest_file_path)
                else:
                    shutil.move(file_path, dest_file_path)
                processed_count += 1
            except Exception as e:
                print(f"Failed to process {file_path}: {e}")

    action = "copied" if copy_files else "moved"
    print(f"Successfully {action} {processed_count} images to '{dest_dir}'.")

if __name__ == "__main__":
    SOURCE_DIRECTORY = "./Data"
    DESTINATION_DIRECTORY = "./Data_by_Patient"
    COPY_FILES = True
    
    print(f"Processing images from '{SOURCE_DIRECTORY}'...")
    redistribute_images(SOURCE_DIRECTORY, DESTINATION_DIRECTORY, copy_files=COPY_FILES)
