import streamlit as st
from db_manager import LabDatabase
import pandas as pd
import glob
import os
from datetime import datetime

# Initialize database
db = LabDatabase()

# Page title
st.set_page_config(page_title = "Lab Database Portal", layout = "wide", page_icon = "static/transparent_LPCG_logo.png")

st.logo("static/LPiGK_transparent.png", size = "large", icon_image = "static/transparent_LPCG_logo.png")

col1, col2 = st.columns([1, 3])

with col1:
    # Mostriamo l'immagine nella prima colonna
    st.image("static/LPiGK_transparent.png", width = 800)

with col2:
    # Mostriamo il titolo nella seconda colonna
    # Aggiungiamo un po' di spazio vuoto sopra se vogliamo allinearlo al centro dell'immagine
    st.markdown("#")
    st.title("Paleogenetics Lab Database Management System")
    st.text("v0.1, by Flavia Leotta (2026)")

st.subheader("", divider = 'orange')
st.sidebar.header("Sections", divider = 'gray')
choice = st.sidebar.radio("Go to:", ["Home page", "Full database", "Upload Data from Excel", "Edit entries", "Backup"])

if choice == "Home page":
    st.subheader("Overview of the database, by individuals")
    try:
        df = pd.read_sql("SELECT * FROM lab_data.individuals_status", db.engine)
        
        if df.empty:
            st.warning("The database is connected, but there is no data to visualize. Upload a file or execute the seed.")
        else:
            st.dataframe(df, width = 'stretch')
            
            st.divider()
            st.subheader("Sampling locations:")
            coordinates = pd.read_sql(f"SELECT coord_ns, coord_we FROM lab_data.individuals", db.engine)
            coordinates = coordinates.dropna()
            if not coordinates.empty:
                st.map(coordinates, latitude = 'coord_ns', longitude = 'coord_we')
            
    except Exception as e:
        st.error(f"Error during data visualization: {e}")

elif choice == "Full database":
    st.subheader("Display table information")
    options = db.get_tables_names()
    selection = st.pills("Tables", options, selection_mode = 'single')

    if selection:
        df = pd.read_sql(f"SELECT * FROM lab_data.{selection}", db.engine)
        
        tsv_data = df.to_csv(sep='\t', index=False).encode('utf-8')
        tsv_file_name = f"table_{selection}.tsv"
        
        st.download_button("Export table in a .tsv format", data = tsv_data, file_name = tsv_file_name)
        st.dataframe(data = df)
    else:
        st.text("Please select one option to display table information.")

elif choice == "Upload Data from Excel":
    st.subheader("Upload files from Excel")
    try:
        with open("templates/template_upload_excel.xlsx", "rb") as f:
            st.download_button("Download Template", f, "template_upload.xlsx")
    except FileNotFoundError:
        st.error("Error: The template file was not found.")
    
    uploaded_file = st.file_uploader("Choose an Excel file (.xlsx)", type = ['xlsx'])
    
    if uploaded_file and st.button("Upload on Database"):
        try:
            # Qui usiamo il metodo che hai intenzione di scrivere nel db_manager
            db.upload_from_excel(uploaded_file)
            st.success(f"Data successfully uploaded!")
        except Exception as e:
            st.error(f"Error during upload: {e}")

elif choice == "Edit entries":
    st.subheader("Edit table information")
    st.text("Warning: this action will overwrite the data and some information will be automatically updated in every table. For example, changing 'lab_id' will affect several tables down the production line , and reversing the change is not always possible. Please proceed with caution: it is recommended you save a backup file before updating any information, as to reverse possible mistakes")
    options = db.get_tables_names()
    selection = st.pills("Tables", options, selection_mode = 'single')

    if selection:
        df = pd.read_sql(f"SELECT * FROM lab_data.{selection}", db.engine)
        st.data_editor(data = df)
    else:
        st.text("Please select one option to display table information.")

elif choice == "Backup":
    st.subheader("Backup management")
    tsv_files = sorted(glob.glob(f"./backups/*tsv"), key = os.path.getctime)
    tsv_files.sort(key = os.path.getctime, reverse = True)
    excel_files = sorted(glob.glob(f"./backups/*xlsx"), key = os.path.getctime)
    excel_files.sort(key = os.path.getctime, reverse = True)

    st.markdown("The backup files are automatically saved everyday at 00:00 (UTC+02:00) on anthill v3.0 server. Here are the latest back-up files available, from most recent to most outdated.")
    st.markdown(" 1. Overview of every individual's status:")

    for file in tsv_files:
        try:
            with open(file, "rb") as f:
                ctime = os.path.getctime(file)
                readable_time = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")

                st.download_button(f"Backup {readable_time}", f, f"Backup_{readable_time}.tsv")
        except FileNotFoundError:
            st.error("Error: No backup .tsv file found.")

    st.markdown(" 2. Excel file for full database:")
    for file in excel_files:
        try:
            with open(file, "rb") as f:
                ctime = os.path.getctime(file)
                readable_time = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")

                st.download_button(f"Backup {readable_time}", f, f"Backup_{readable_time}.xlsx")
        except FileNotFoundError:
            st.error("Error: No backup .xlsx file found.")
    
    st.markdown("###")
    st.subheader("Want to backup the server right now?")
    if st.button("Execute the backup now"):
        db.run_backup()
        st.success("Backup SQL, CSV and XLSX correctly generated!")