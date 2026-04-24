import streamlit as st
from db_manager import LabDatabase
import pandas as pd
import glob
import os
from datetime import datetime
import plotly.express as px
from sqlalchemy import text

@st.cache_resource
def get_database_connection():
    # Sostituisci con la tua logica di inizializzazione
    return LabDatabase()

db = get_database_connection()

# Cached memory
@st.cache_data
def get_individuals_status(_db_engine):
    # L'ordinamento lo facciamo qui!
    query = "SELECT * FROM lab_data.individuals_status ORDER BY lab_id"
    return pd.read_sql(query, _db_engine)

@st.cache_data
def get_map_coordinates(_db_engine):
    """Scarica le coordinate e le salva in memoria."""
    query = "SELECT lab_id, coord_ns, coord_we FROM lab_data.individuals"
    return pd.read_sql(query, _db_engine).dropna()

@st.cache_data
def get_any_table(_db_engine, table_name):
    query = f"SELECT * FROM lab_data.{table_name}"
    return pd.read_sql(query, _db_engine)

@st.cache_data
def get_backup_files(path, extension):
    files = glob.glob(f"{path}/*.{extension}")
    # Ordiniamo per data di creazione (più recente prima)
    return sorted(files, key=os.path.getctime, reverse=True)

# Page title
st.set_page_config(page_title = "Lab Database Portal", layout = "wide", page_icon = "static/transparent_LPCG_logo.png")
st.logo("static/LPiGK_transparent.png", size = "large", icon_image = "static/transparent_LPCG_logo.png")

col1, col2 = st.columns([1, 3])
with col1:
    st.image("static/LPiGK_transparent.png", width = 800)
with col2:
    st.markdown("#")
    st.title("Paleogenetics Lab Database Management System")
    st.text("v0.1, by Flavia Leotta (2026)")
st.subheader("", divider = 'orange')
# st.sidebar.header("Sections", divider = 'gray')
# choice = st.sidebar.radio("Go to:", ["Home page", "Full database", "Upload Data from Excel", "Edit entries", "Backup"])

# Defining pages:
def home_page():
#if choice == "Home page":
    st.subheader("Home page")
    
    try:
        df = get_individuals_status(db.engine)
        coords_all = get_map_coordinates(db.engine)

        # --- 1. FUNZIONE DI RICERCA MULTI-ID ---
        search_input = st.text_input("🔍 Search by Lab ID (separate multiple IDs with commas):", "").strip().upper()

        if search_input:
            # Dividiamo la stringa per virgola e puliamo gli spazi per ogni ID
            # Esempio: "PL001,  PL005" -> ["PL001", "PL005"]
            search_list = [id.strip() for id in search_input.split(",") if id.strip()]
            
            # Filtriamo il dataframe: cerchiamo tutti i campioni che CONTENGONO una delle stringhe inserite
            # In industria si usa la regex (Regular Expression) per fare ricerche multiple veloci
            import re
            regex_search = "|".join(map(re.escape, search_list)) # Crea una stringa tipo "PL001|PL005"
            df_filtered = df[df['lab_id'].str.contains(regex_search, na=False, regex=True)]
            st.caption(f"Found {len(df_filtered)} samples matching your search criteria.")
        else:
            df_filtered = df

        # --- 2. LOGICA DI PAGINAZIONE ---
        rows_per_page = 15
        total_rows = len(df_filtered)
        total_pages = (total_rows // rows_per_page) + (1 if total_rows % rows_per_page > 0 else 0)

        # Inizializziamo il numero di pagina nello stato della sessione
        if 'current_page' not in st.session_state:
            st.session_state.current_page = 1

        # Controllo per non finire fuori dalle pagine se il filtro riduce i risultati
        if st.session_state.current_page > total_pages and total_pages > 0:
            st.session_state.current_page = total_pages

        # Layout per i pulsanti di navigazione
        _, btn_prev, _, page_text, _, btn_next = st.columns([2, 1, 1, 2, 1, 1])

        with btn_prev:
            if st.button("⬅️", width='stretch') and st.session_state.current_page > 1:
                st.session_state.current_page -= 1
                st.rerun()

        with page_text:
            st.markdown(f"<p style='text-align: center; padding-top: 5px;'>Page <b>{st.session_state.current_page}</b> / {total_pages}</p>", unsafe_allow_html=True)

        with btn_next:
            if st.button("➡️", width='stretch') and st.session_state.current_page < total_pages:
                st.session_state.current_page += 1
                st.rerun()

        # Calcolo degli indici per la "fetta" di dati (slicing)
        start_idx = (st.session_state.current_page - 1) * rows_per_page
        end_idx = start_idx + rows_per_page
        df_page = df_filtered.iloc[start_idx:end_idx]

        # --- 3. VISUALIZZAZIONE ---
        col_left, col_right = st.columns([1, 3])

        with col_right:
            if df_page.empty:
                st.warning("No samples found matching your search.")
            else:
                event = st.dataframe(
                    df_page, 
                    width='stretch',
                    on_select="rerun",
                    selection_mode="multi-row",
                    height=565 # Altezza fissa calibrata per circa 15 righe
                )
                
                selected_indices = event.selection.rows
                selected_ids = [df_page.iloc[i]['lab_id'] for i in selected_indices] if selected_indices else []

        with col_left:
            with st.expander("📍 Map View", expanded=True):
                # Se l'utente ha cercato qualcosa, la mappa mostra solo i risultati della ricerca
                # Se ha anche selezionato righe, mostra solo le selezionate
                map_source = coords_all[coords_all['lab_id'].isin(df_filtered['lab_id'])]
                
                if selected_ids:
                    map_data = map_source[map_source['lab_id'].isin(selected_ids)]
                else:
                    map_data = map_source
                
                st.map(map_data, latitude='coord_ns', longitude='coord_we')

    except Exception as e:
        st.error(f"Error: {e}")

def full_db():
#elif choice == "Full database":
    st.subheader("Full Database")
    options = db.get_tables_names()
    selection = st.pills("Tables", options, selection_mode = 'single')

    if selection:
        df = get_any_table(db.engine, selection)
        
        tsv_data = df.to_csv(sep='\t', index=False).encode('utf-8')
        tsv_file_name = f"table_{selection}.tsv"
        
        st.download_button("Export table in a .tsv format", data = tsv_data, file_name = tsv_file_name)
        st.dataframe(data = df)
    else:
        st.text("Please select one option to display table information.")

def upload_data():
#elif choice == "Upload Data from Excel":
    st.subheader("Upload Excel")
    try:
        with open("templates/template_upload_excel.xlsx", "rb") as f:
            st.download_button("Download Template", f, "template_upload.xlsx")
    except FileNotFoundError:
        st.error("Error: The template file was not found.")
    
    uploaded_file = st.file_uploader("Choose an Excel file (.xlsx)", type = ['xlsx'])
    
    if uploaded_file and st.button("Upload on Database"):
        try:
            db.upload_from_excel(uploaded_file)

            st.cache_data.clear()

            st.success(f"Data successfully uploaded!")
        except Exception as e:
            st.error(f"Error during upload: {e}")

def edit_entries():
#elif choice == "Edit entries":
    st.subheader("Edit entries")
    
    options = db.get_tables_names()
    selection = st.pills("Select Table", options, selection_mode='single')

    if selection:
        # 1. CONTROLLO CACHE INTERNA: Carichiamo dal DB solo se la tabella è cambiata
        if "last_selection" not in st.session_state or st.session_state.last_selection != selection:
            with st.spinner(f"Loading {selection}..."):
                st.session_state.df_to_edit = pd.read_sql(f"SELECT * FROM lab_data.{selection}", db.engine)
                st.session_state.last_selection = selection

        # 2. L'EDITOR usa i dati in memoria (super veloce)
        # Disabilitiamo il 'rerun' ad ogni clic per massima fluidità
        edited_df = st.data_editor(
            st.session_state.df_to_edit, 
            width='stretch', 
            num_rows="fixed",
            key="my_editor" # La chiave fissa aiuta Streamlit a non perdere lo stato
        )
        
        # 3. SALVATAGGIO
        if st.button("💾 Save all changes"):
            with st.spinner("Synchronizing with Database..."):
                success = db.safe_update_table(selection, edited_df)
                if success:
                    st.success("Database updated!")
                    # Aggiorniamo la memoria interna con i nuovi dati salvati
                    st.session_state.df_to_edit = edited_df.copy()
                    st.cache_data.clear() # Svuota il cache per le altre pagine
    else:
        st.text("Please select one option to start editing.")

def backup():
    st.subheader("💾 Backup Management")
    st.text("The backup files are automatically saved every day at 00:00 (UTC+02:00) on anthill v3.0 server.")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 1. TSV Overviews")
        tsv_files = get_backup_files("./backups", "tsv")
        
        if tsv_files:
            # Creiamo il menu a comparsa
            with st.popover("📂 Select TSV Backup"):
                for file in tsv_files:
                    ctime = os.path.getctime(file)
                    readable_time = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")
                    filename = os.path.basename(file)
                    
                    with open(file, "rb") as f:
                        st.download_button(
                            label=f"📄 {readable_time}",
                            data=f,
                            file_name=filename,
                            key=f"dl_tsv_{filename}" # Chiave unica per evitare conflitti
                        )
        else:
            st.warning("No .tsv backups found.")

    with col2:
        st.markdown("### 2. Excel Full DB")
        excel_files = get_backup_files("./backups", "xlsx")
        
        if excel_files:
            # Altro menu a comparsa per gli Excel
            with st.popover("📊 Select Excel Backup"):
                for file in excel_files:
                    ctime = os.path.getctime(file)
                    readable_time = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")
                    filename = os.path.basename(file)
                    
                    with open(file, "rb") as f:
                        st.download_button(
                            label=f"📗 {readable_time}",
                            data=f,
                            file_name=filename,
                            key=f"dl_xlsx_{filename}"
                        )
        else:
            st.warning("No .xlsx backups found.")

    st.divider()
    
    # Sezione Backup Manuale
    st.subheader("🚀 Manual Sync")
    st.write("Need a snapshot of the database right now?")
    if st.button("Execute the backup now", type="primary"):
        with st.spinner("Generating backup files..."):
            db.run_backup()
            st.success("Backup SQL, CSV and XLSX correctly generated!")
            st.rerun() # Ricarica la pagina per vedere i nuovi file nei popover

def sample_view():
    st.title("🧬 Sample Detailed View")
    
    # 1. Ricerca del Lab ID
    # Suggerimento: potresti caricare la lista di tutti i lab_id per un autocomplete
    all_ids = db.get_column_values("individuals", columns = "lab_id")
    target_id = st.selectbox("Search for a Lab ID:", [""] + all_ids, placeholder = "Start typing a lab_id...", filter_mode = "prefix")

    if target_id:
        data = db.get_sample_details(target_id)
        
        if data.empty:
            st.warning("No data found for this ID.")
            return

        # Prendiamo la prima riga per le info generali
        info = data.iloc[0]

        # Header con info principali
        col1, col2, col3= st.columns(3)
        col1.metric("Lab ID", info['lab_id'])
        col2.metric("Project", info['project_id'])
        col3.metric("Site", info['site_name'])

        st.divider()

        # 2. Organizzazione in TABS
        tab1, tab2, tab3 = st.tabs(["🏛 Context & Origin", "🧪 Lab Process", "📊 Sequencing Results"])

        with tab1:
            st.subheader("Archeological Context")
            c1, c2 = st.columns(2)
            c1.write(f"**Epoch:** {info.get('epoch', 'Unknown')}")
            c1.write(f"**Period:** {info.get('time_period', 'Unknown')}")
            c2.write(f"**Grave No:** {info.get('grave_no', 'N/A')}")
            c2.write(f"**Contact Person:** {info.get('contact_person', 'N/A')}")
            
            if info.get('coord_ns') and info.get('coord_we'):
                # Piccola mappa se ci sono coordinate
                map_data = pd.DataFrame({'lat': [info['coord_ns']], 'lon': [info['coord_we']]})
                st.map(map_data, zoom=4)

        with tab2:
            st.subheader("Laboratory History")
            # Mostriamo i passaggi chiave
            with st.expander("Sampled Materials (Processed Samples)", expanded=True):
                # Estraiamo solo le colonne relative ai campioni processati e togliamo i duplicati
                materials_df = data[['material_id', 'material_description', 'prep_date', 'prep_operator']].drop_duplicates().dropna(subset=['material_id'])
                
                if not materials_df.empty:
                    st.dataframe(materials_df, width='stretch', hide_index=True)
                else:
                    st.info("No processed samples found for this individual.")
            
            st.write(f"**Extraction Date:** {info.get('extract_date', 'Not yet extracted')}")
            st.write(f"**Operator:** {info.get('extract_operator', '-')}")
            st.write(f"**Method:** {info.get('extract_method', '-')}")
            
            st.divider()
            st.write("**Library Information:**")
            # Se ci sono più librerie per lo stesso campione, qui data avrà più righe
            st.table(data[['library_id', 'library_type', 'library_operator']].drop_duplicates().dropna())

        with tab3:
            st.subheader("Bioinformatics Overview")
            if pd.notnull(info.get('fastq_name')):
                c1, c2, c3 = st.columns(3)
                c1.metric("Raw Reads", f"{info.get('raw_reads', 0):,}")
                c2.metric("Mapped Reads", f"{info.get('tot_reads_map', 0):,}")
                c3.metric("Endogenous DNA", f"{info.get('endo_dna', 0)}%")
                
                st.write(f"**Fastq Name:** `{info['fastq_name']}`")
            else:
                st.info("Sequencing data not yet available for this sample.")

def project_view():
    st.title("📁 Project Management Overview")
    
    # 1. Recupero lista progetti
    project_list = db.get_column_values("individuals", columns="project_id")
    selected_project = st.selectbox("Select Project:", [""] + project_list)
    
    if selected_project:
        # 2. Statistiche KPI
        stats_df = db.get_project_stats(selected_project)
        if not stats_df.empty:
            stats = stats_df.iloc[0]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Individuals", stats['total_individuals'])
            c2.metric("Extractions", stats['total_extractions'])
            c3.metric("Libraries", stats['total_libraries'])
            
            # Formattazione carina per l'endogeno
            endo = stats['avg_endogenous']
            c4.metric("Avg Endogenous", f"{endo:.2f}%" if endo is not None else "N/A")

        st.divider()
        
        # 3. Recupero dati con sintassi corretta per SQLAlchemy 2.0
        # Usiamo text() e conn.execute per essere sicuri che :pid venga letto
        query = text("SELECT * FROM lab_data.individuals WHERE project_id = :pid")
        mat_query = text("""
            SELECT ps.material_description 
            FROM lab_data.processed_samples ps
            JOIN lab_data.individuals i ON ps.lab_id = i.lab_id
            WHERE i.project_id = :pid
        """)

        try:
            with db.engine.connect() as conn:
                # Carichiamo i dati degli individui
                full_data = pd.read_sql(query, conn, params={"pid": selected_project})
                # Carichiamo i dati dei materiali
                mat_data = pd.read_sql(mat_query, conn, params={"pid": selected_project})
        except Exception as e:
            st.error(f"Errore nel database: {e}")
            return

        # 4. Visualizzazione Tab
        tab1, tab2 = st.tabs(["📊 Analytics", "📋 Sample List"])
        
        with tab1:
            col_a, col_b = st.columns(2)
            
            with col_a:
                st.subheader("Distribution by Site")
                if not full_data.empty and 'site_name' in full_data.columns:
                    site_counts = full_data['site_name'].value_counts().reset_index()
                    site_counts.columns = ['site_name', 'count']
                    fig_site = px.pie(site_counts, names='site_name', values='count', hole=0.4,
                                    color_discrete_sequence=px.colors.qualitative.Pastel)
                    st.plotly_chart(fig_site, width='stretch')
                else:
                    st.info("No site data available.")
                
            with col_b:
                st.subheader("Samples by Material")
                if not mat_data.empty:
                    mat_counts = mat_data['material_description'].value_counts().reset_index()
                    mat_counts.columns = ['material', 'count']
                    fig_mat = px.bar(mat_counts, x='count', y='material', orientation='h', 
                                   color='material', color_discrete_sequence=px.colors.qualitative.Safe)
                    # Miglioriamo il layout del grafico a barre
                    fig_mat.update_layout(showlegend=False, yaxis={'categoryorder':'total ascending'})
                    st.plotly_chart(fig_mat, width='stretch')
                else:
                    st.info("No material records for this project.")

        with tab2:
            st.subheader("Complete Project Records")
            st.dataframe(full_data, width='stretch', hide_index=True)
            
            # Export CSV
            csv = full_data.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=f"{selected_project.replace(' ', '_')}_data.csv",
                mime="text/csv",
            )


# 3. CONFIGURAZIONE NAVIGAZIONE
# Puoi dividere le pagine in gruppi (sezioni)
pg = st.navigation({
    "Management": [
        st.Page(home_page, title="Home", icon="🏠"),
        st.Page(full_db, title="Full Database", icon="📊"),
    ],
    "Data Entry": [
        st.Page(upload_data, title="Upload Excel", icon="📤"),
        st.Page(edit_entries, title="Edit Entries", icon="📝"),
    ],
    "Deep Dive": [
        st.Page(sample_view, title="Sample View", icon="🧬"),
        st.Page(project_view, title="Project View", icon="📁"),
    ],
    "System": [
        st.Page(backup, title="Backup", icon="💾"),
    ]
})




# 4. ESECUZIONE
pg.run()