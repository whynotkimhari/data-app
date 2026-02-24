# MRI Bounding Box Review - Doctor Setup

Welcome! This tool allows you to review and manage MRI bounding box annotations. 
It uses Docker to ensure it works identically on any computer.

## Requirements
* You need **Docker Desktop** installed on your computer. 
* *Download here if you don't have it:* https://www.docker.com/products/docker-desktop/

## How to Run the App
0. Download data: 
   - OASIS: https://www.kaggle.com/datasets/ninadaithal/imagesoasis/data
   - AI in Dementia Project: https://docs.google.com/spreadsheets/d/18P0Rvsmn8QMGGiuYbB_QUf4XNQ6zuetAPQXC04gdL-4/edit?usp=sharing
   - move downloaded data into this folder
   - run `python distribute_images.py`
1. Open your computer's terminal (or Command Prompt).
2. Navigate to this folder (`data-app`).
3. Run the following command:
   ```bash
   docker-compose up -d --build
   ```
4. Wait a few moments for the app to start up.
5. Open your web browser and go to:
   👉 **http://localhost:8501**

## Where is my data saved?
Every time you accept a bounding box or write doctor's notes, it is automatically and instantly saved to your computer.

You can find the saved labels as a simple JSON file right here:
👉 **`results/accepted_labels.json`**

*(Note: Never delete this file unless you want to erase all your accepted labels.)*

## How to Stop the App
When you are done for the day, go back to your terminal and simply run:
```bash
docker-compose down
```
