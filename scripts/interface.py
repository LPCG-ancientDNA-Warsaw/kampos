import streamlit as st
from db_manager import LabDatabase
import pandas as pd

# Initialize database
db = LabDatabase()

# Page title
st.set_page_config(page_title = "Lab Database Portal", layout = "wide", page_icon = "static/transparent_LPCG_logo.png")

st.title("Paleogenetics Lab Database Management System")
st.sidebar.header("Sections")
choice = st.sidebar.radio("Go to:", ["Home page", "Upload Data from Excel", "Backup"])

if choice == "Home page":
    st.subheader("Overview of the database, by individuals")
    try:
        df = pd.read_sql("SELECT * FROM lab_data.individuals_status", db.engine)
        
        if df.empty:
            st.warning("The database is connected, but there is no data to visualize. Upload a file or execute the seed.")
        else:
            st.dataframe(df, use_container_width = True)
            
            # Mostriamo un grafico solo se ci sono dati numerici
            if 'num_extractions' in df.columns:
                st.bar_chart(df.set_index('lab_id')['num_extractions'])
            
    except Exception as e:
        st.error(f"Error during data visualization: {e}")

elif choice == "Upload Data from Excel":
    st.subheader("Upload files from Excel")
    uploaded_file = st.file_uploader("Choose an Excel file (.xlsx)", type=['xlsx'])
    
    table_target = st.selectbox("In which table do you want to upload your data?", 
                                ["sampling_sites", "individuals", "processed_samples"])
    
    if uploaded_file and st.button("Upload on Database"):
        try:
            # Qui usiamo il metodo che hai intenzione di scrivere nel db_manager
            db.upload_from_excel(uploaded_file, table_target)
            st.success(f"Data successfully upload on the target table: {table_target}!")
        except Exception as e:
            st.error(f"Error during upload: {e}")

elif choice == "Backup":
    st.subheader("Backup management")
    if st.button("Execute the backup now"):
        db.run_backup()
        st.success("Backup SQL and CSV correctly generated!")