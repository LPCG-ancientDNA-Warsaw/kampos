import streamlit as st
from db_manager import LabDatabase
import pandas as pd
import glob
import os
from datetime import datetime
import plotly.express as px
from sqlalchemy import text

@st.cache_resource(show_spinner="Connecting to the database...")
def init_db(user, password):
    db = LabDatabase(user=user, password=password)
    with db.engine.connect() as conn:
        pass
    
    return db

def get_database_connection():
    st.sidebar.title("Database Access")
    db_user = st.sidebar.text_input("Username Database")
    db_password = st.sidebar.text_input("Password Database", type="password")

    if db_user and db_password:
        try:
            db = init_db(db_user, db_password)
            st.sidebar.success("Connection established!")
            return db
        
        except Exception as e:
            st.sidebar.error("Impossible to establish a connection: check your credentials or the database's status.")
            return None
    else:
        st.warning("Please provide your credentials.")
        return None

db = get_database_connection()

if db:
    st.write(f"Welcome to database **{db.db_name}**!")

# Cached memory
@st.cache_data
def get_individuals_status(_db_engine):
    all_individual_ids = db.get_column_values(
        table=db.config["database"]["mapping"]["individual_id"]["base_table"],
        columns=db.config["database"]["mapping"]["individual_id"]["column_name"],)

    requested_fields = [
        "individual_id",
        "material_id",
        "prep_date",
        "extract_date",
        "library_id",
        "raw_reads",
        "endo_dna",
        "tot_reads_map",
        ]
    
    details_frames = []
    for individual_id in all_individual_ids:
        df = db.get_sample_details(individual_id)
        if df.empty:
            continue
    
        if "individual_id" not in df.columns:
            df = df.copy()
            df["individual_id"] = individual_id
    
        df = df.reindex(columns=requested_fields, fill_value=pd.NA)
        details_frames.append(df)
    
    if details_frames:
        combined_df = pd.concat(details_frames, ignore_index=True)

    return combined_df

@st.cache_data
def get_map_coordinates(_db_engine):
    """Scarica le coordinate e le salva in memoria."""
    individual_id_column_name = db.config["database"]["mapping"]["individual_id"]["column_name"]
    individual_id_table = db.config["database"]["mapping"]["individual_id"]["base_table"]
    coord_ns_info = db.config["database"]["mapping"]["coord_ns"]
    coord_we_info =  db.config["database"]["mapping"]["coord_we"]
    coords_table = coord_ns_info["base_table"]

    if not individual_id_column_name or not individual_id_table:
        raise ValueError("The mapping for individual_id is incomplete in config.json")

    if not coord_ns_info.get("column_name") or not coord_we_info.get("column_name"):
        raise ValueError("The mapping for coord_ns/coord_we is incomplete in config.json")


    if str(individual_id_table).lower() == str(coords_table).lower():
        query = f"""
        SELECT {individual_id_column_name} AS individual_id,
               {coord_ns_info["column_name"]} AS coord_ns, 
               {coord_we_info["column_name"]} AS coord_we
        FROM {db.schema}.{individual_id_table}
        """
    else:
        query = f"""
        SELECT i.{individual_id_column_name} AS individual_id, 
               c.{coord_ns_info["column_name"]} AS coord_ns,
               c.{coord_we_info["column_name"]} AS coord_we
        FROM {db.schema}.{individual_id_table} AS i
        LEFT JOIN {db.schema}.{coords_table} AS c
        ON i.{individual_id_column_name} = c.{individual_id_column_name}
        """
    
    return pd.read_sql(query, _db_engine).dropna()

@st.cache_data
def get_any_table(_db_engine, table_name):
    query = f"SELECT * FROM {db.schema}.{table_name}"
    return pd.read_sql(query, _db_engine)

@st.cache_data
def get_backup_files(path, extension):
    files = glob.glob(f"{path}/*.{extension}")
    # Ordiniamo per data di creazione (più recente prima)
    return sorted(files, key=os.path.getctime, reverse=True)

# Page title
st.set_page_config(page_title = "Kampos: Lab Database Portal", layout = "wide", page_icon = "static/transparent_LPCG_logo.png")
st.logo("static/LPiGK_transparent.png", size = "large", icon_image = "static/transparent_LPCG_logo.png")

col1, col2 = st.columns([1, 3])
with col1:
    st.image("static/LPiGK_transparent.png", width = 800)
with col2:
    st.markdown("#")
    st.title("Kampos: Keep All Metadata Properly and Orderly Stored")
    st.text("v0.1, by Flavia Leotta (2026)")
st.subheader("", divider = 'orange')
# st.sidebar.header("Sections", divider = 'gray')
# choice = st.sidebar.radio("Go to:", ["Home page", "Full database", "Upload Data from Excel", "Edit entries", "Backup"])

# Defining pages:
def home_page():
#if choice == "Home page":
    st.subheader("Home page")
    #### General useful information
    
    try:
        
        df = get_individuals_status(db.engine)
        print("HOME: returned dataframe shape", df.shape)
        coords_all = get_map_coordinates(db.engine)
        print("HOME: returned dataframe shape", coords_all.shape)

        # --- 1. FUNZIONE DI RICERCA MULTI-ID ---
        search_input = st.text_input("🔍 Search by Individual ID (separate multiple IDs with commas):", "").strip().upper()

        if search_input:
            # Dividiamo la stringa per virgola e puliamo gli spazi per ogni ID
            # Esempio: "PL001,  PL005" -> ["PL001", "PL005"]
            search_list = [id.strip() for id in search_input.split(",") if id.strip()]
            
            # Filtriamo il dataframe: cerchiamo tutti i campioni che CONTENGONO una delle stringhe inserite
            # In industria si usa la regex (Regular Expression) per fare ricerche multiple veloci
            import re
            regex_search = "|".join(map(re.escape, search_list)) # Crea una stringa tipo "PL001|PL005"
            df_filtered = df[df["individual_id"].str.contains(regex_search, na=False, regex=True)]
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
                selected_ids = [df_page.iloc[i]["individual_id"] for i in selected_indices] if selected_indices else []

        with col_left:
            with st.expander("📍 Map View", expanded=True):
                # Se l'utente ha cercato qualcosa, la mappa mostra solo i risultati della ricerca
                # Se ha anche selezionato righe, mostra solo le selezionate
                
                map_source = coords_all[coords_all["individual_id"].isin(df_filtered["individual_id"])]
                
                if selected_ids:
                    map_data = map_source[map_source["individual_id"].isin(selected_ids)]
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
                st.session_state.df_to_edit = pd.read_sql(f"SELECT * FROM {db.schema}.{selection}", db.engine)
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
                    st.cache_data.clear()
    else:
        st.text("Please select one option to start editing.")

def backup():
    st.subheader("💾 Backup Management")
    st.text("The backup files are automatically saved at the first edit of the day.")

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
            st.success("Backup CSV and XLSX correctly generated!")
            st.cache_data.clear()
            st.rerun() 

def sample_view():
    st.title("🧬 Sample Detailed View")
    id_info = db.config["database"]["mapping"]["individual_id"]
    # 1. Ricerca del Lab ID
    # Suggerimento: potresti caricare la lista di tutti i lab_id per un autocomplete
    all_ids = db.get_column_values(table=id_info["base_table"], columns=id_info["column_name"])
    target_id = st.selectbox("Search for a Lab ID:", [""] + all_ids, placeholder = "Start typing an individual ID...", filter_mode = "prefix")

    
    if target_id:
        data = db.get_long_sample_details(target_id)
        print(data)

        if data.empty:
            st.warning("No data found for this ID.")
            return

        # Prendiamo la prima riga per le info generali
        data = data.loc[:, ~data.columns.duplicated()]

        def get_scalar_val(df, col_name, default="N/A"):
            if col_name in df.columns and not df[col_name].empty:
                val = df[col_name].dropna().iloc[0] if not df[col_name].dropna().empty else None
                if val is not None:
                    return str(val)
    
            return default

        # Header con info principali
        col1, col2, col3 = st.columns(3)
        col1.metric("Individual ID", get_scalar_val(data, 'individual_id'))
        col2.metric("Project", get_scalar_val(data, 'project_id'))
        col3.metric("Site", get_scalar_val(data, 'site_name'))

        st.divider()

        # 2. Organizzazione in TABS
        tab1, tab2, tab3 = st.tabs(["🏛 Context & Origin", "🧪 Lab Process", "📊 Sequencing Results"])

        with tab1:
            st.subheader("Archeological Context")
            c1, c2 = st.columns(2)
            c1.write(f"**Epoch:** {get_scalar_val(data, 'epoch', 'Unknown')}")
            c1.write(f"**Period:** {get_scalar_val(data, 'time_period', 'Unknown')}")
            c2.write(f"**Grave No:** {get_scalar_val(data, 'grave_no', 'N/A')}")
            c2.write(f"**Contact Person:** {get_scalar_val(data, 'contact_person', 'N/A')}")

            coord_ns = get_scalar_val(data, 'coord_ns', None)
            coord_we = get_scalar_val(data, 'coord_we', None)
            
            if coord_ns and coord_we:
                try:
                    map_data = pd.DataFrame({'lat': [float(coord_ns)], 'lon': [float(coord_we)]})
                    st.map(map_data, zoom=4)
                except ValueError:
                    st.caption("Coordinates available but not in valid numeric format.")

        with tab2:
            st.subheader("Laboratory History")
            # Mostriamo i passaggi chiave
# --- Section A: Materiali campionati ---
            with st.expander("Sampled Materials (Processed Samples)", expanded=True):
                mat_cols = [c for c in ['material_id', 'material_description', 'prep_date', 'prep_operator'] if c in data.columns]
                if mat_cols:
                    materials_df = data[mat_cols].drop_duplicates().dropna(how='all')
                    if not materials_df.empty:
                        st.dataframe(materials_df, width="stretch", hide_index=True)
                    else:
                        st.info("No processed samples found for this individual.")

            # --- Section B: Estrazioni DNA (Supporto a estrazioni multiple) ---
            st.markdown("#### 🧬 DNA Extractions")
            extract_cols = [c for c in ['individual_id', 'material_id', 'extract_date', 'extract_operator', 'extract_method'] if c in data.columns]
            
            # Se la colonna extract_id esiste, filtriamo per quella, altrimenti usiamo le altre info
            if extract_cols:
                extractions_df = data[extract_cols].drop_duplicates().dropna(how='all')
                if not extractions_df.empty:
                    st.dataframe(extractions_df, width="stretch", hide_index=True)
                else:
                    st.info("No DNA extraction records found.")
            else:
                st.info("No extraction columns mapped.")

            st.divider()

            # --- Section C: Librerie (Supporto a librerie multiple) ---
            st.markdown("#### 🧪 Library Preparation")
            lib_cols = [c for c in ['library_id', 'library_type', 'library_operator', 'library_date'] if c in data.columns]
            if lib_cols:
                libraries_df = data[lib_cols].drop_duplicates().dropna(how='all')
                if not libraries_df.empty:
                    st.dataframe(libraries_df, width="stretch", hide_index=True)
                else:
                    st.info("No library preparation records found.")

        # TAB 3: RISULTATI DI SEQUENZIAMENTO E BIOINFORMATICA
        with tab3:
            st.subheader("Bioinformatics Overview")
            
            seq_cols = [c for c in ['fastq_name', 'raw_reads', 'tot_reads_map', 'endo_dna'] if c in data.columns]
            seq_data = data[seq_cols].drop_duplicates().dropna(subset=['fastq_name']) if 'fastq_name' in data.columns else pd.DataFrame()

            if not seq_data.empty:
                # Calcoliamo i totali/riassunti su tutti i runs di sequenziamento
                tot_raw = seq_data['raw_reads'].sum() if 'raw_reads' in seq_data.columns else 0
                tot_mapped = seq_data['tot_reads_map'].sum() if 'tot_reads_map' in seq_data.columns else 0
                avg_endo = seq_data['endo_dna'].mean() if 'endo_dna' in seq_data.columns else 0

                c1, c2, c3 = st.columns(3)
                c1.metric("Total Raw Reads", f"{int(tot_raw):,}" if pd.notnull(tot_raw) else "0")
                c2.metric("Total Mapped Reads", f"{int(tot_mapped):,}" if pd.notnull(tot_mapped) else "0")
                c3.metric("Avg Endogenous DNA", f"{avg_endo:.2f}%" if pd.notnull(avg_endo) else "N/A")

                st.markdown("#### FASTQ Files & Details")
                st.dataframe(seq_data, width="stretch", hide_index=True)
            else:
                st.info("Sequencing data not yet available for this sample.")

def project_view():
    st.title("📁 Project Management Overview")
    
    # 1. Recupero lista progetti
    project_info = db.config["database"]["mapping"]["project_id"]
    project_list = db.get_column_values(table=project_info["base_table"], columns=project_info["column_name"])
    selected_project = st.selectbox("Select Project:", [""] + project_list)
    
    if selected_project:
        # 2. Statistiche KPI
        stats_df = db.get_project_details(selected_project)
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
        individual_info = db.config["database"]["mapping"]["individual_id"]
        project_info = db.config["database"]["mapping"]["project_id"]
        material_info = db.config["database"]["mapping"]["material_description"]

        individual_table = individual_info.get("base_table")
        individual_key_col = individual_info.get("column_name")
        project_col = project_info.get("column_name")

        query = text(f"""
            SELECT *
            FROM {db.schema}.{individual_table}
            WHERE {project_col} = :pid
        """)

        mat_query = text(f"""
            SELECT ps.{material_info["column_table"]}
            FROM {db.schema}.{material_info["base_table"]} ps
            JOIN {db.schema}.{individual_table} i
            ON ps.{individual_key_col} = i.{individual_key_col}
            WHERE i.{project_col} = :pid
        """)

        try:
            with db.engine.connect() as conn:
                # Carichiamo i dati degli individui
                full_data = pd.read_sql(query, conn, params={"pid": selected_project})
                # Carichiamo i dati dei materiali
                mat_data = pd.read_sql(mat_query, conn, params={"pid": selected_project})
        except Exception as e:
            st.error(f"Error in database: {e}")
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