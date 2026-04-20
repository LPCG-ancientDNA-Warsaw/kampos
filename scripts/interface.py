import streamlit as st
from db_manager import LabDatabase
import pandas as pd

# Initialize database
db = LabDatabase()

st.set_page_config(page_title = "Lab Database Portal", layout = "wide")

st.title("Lab Database Management System")
st.sidebar.header("Navigazione")
choice = st.sidebar.radio("Vai a:", ["Dashboard", "Carica Dati", "Backup"])

if choice == "Dashboard":
    st.subheader("Stato del Campionamento")
    try:
        df = pd.read_sql("SELECT * FROM lab_data.individuals_status", db.engine)
        
        if df.empty:
            st.warning("⚠️ Il database è connesso, ma non ci sono dati da visualizzare. Carica un file Excel o esegui il seed!")
        else:
            st.dataframe(df, use_container_width=True)
            
            # Mostriamo un grafico solo se ci sono dati numerici
            if 'num_extractions' in df.columns:
                st.bar_chart(df.set_index('lab_id')['num_extractions'])
    except Exception as e:
        st.error(f"❌ Errore durante la lettura dei dati: {e}")

elif choice == "Carica Dati":
    st.subheader("Caricamento nuovi dati da Excel")
    uploaded_file = st.file_uploader("Scegli un file Excel", type=['xlsx'])
    
    table_target = st.selectbox("In quale tabella vuoi caricare i dati?", 
                                ["sampling_sites", "individuals", "processed_samples"])
    
    if uploaded_file and st.button("Carica su Database"):
        try:
            # Qui usiamo il metodo che hai intenzione di scrivere nel db_manager
            db.upload_from_excel(uploaded_file, table_target)
            st.success(f"Dati caricati con successo in {table_target}!")
        except Exception as e:
            st.error(f"Errore durante il caricamento: {e}")

elif choice == "Backup":
    st.subheader("Gestione Backup")
    if st.button("Esegui Backup Ora"):
        db.run_backup()
        st.success("Backup SQL e CSV generati correttamente!")