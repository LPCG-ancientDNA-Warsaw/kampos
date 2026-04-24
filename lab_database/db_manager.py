import os
import pandas as pd
from sqlalchemy import create_engine, event, inspect, text
import sqlalchemy
from dotenv import load_dotenv  # Can read the .env file
import subprocess               # For the backup system
import shutil
import glob
from datetime import datetime

load_dotenv()

class LabDatabase:
    def __init__(self):
        self.user = os.getenv("DB_USER")
        self.password = os.getenv("DB_PASSWORD")
        self.host = os.getenv("DB_HOST")
        self.port = os.getenv("DB_PORT")
        self.db_name = os.getenv("DB_NAME")
        self.url = f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}"

        self.engine = create_engine(self.url)
    
    def get_column_values(self, table, schema = 'lab_data', columns='all'):
        with self.engine.connect() as conn:
            try:
                if columns == 'all':
                    result = pd.read_sql(f"SELECT * FROM lab_data.{table}", conn)
                
                if isinstance(columns, list):
                    if len(columns) == 1:
                        # Una sola colonna in una lista -> Restituisce una lista Python
                        col_name = columns[0]
                        df = pd.read_sql(text(f"SELECT {col_name} FROM {schema}.{table}"), conn)
                        return df[col_name].dropna().unique().tolist()
                    else:
                        # Più colonne -> Restituisce un DataFrame filtrato
                        cols_str = ", ".join(columns)
                        return pd.read_sql(text(f"SELECT {cols_str} FROM {schema}.{table}"), conn)
                
                elif isinstance(columns, str):
                    # Una stringa singola -> Restituisce una lista Python
                    df = pd.read_sql(text(f"SELECT {columns} FROM {schema}.{table}"), conn)
                    return df[columns].dropna().unique().tolist()
                
                else:
                    print("Error: 'columns' must be a string or a list.")
                    return None

            except Exception as e:
                print(f"Error with the database: {e}")
                return None
            

    
    def get_sample_details(self, lab_id):
        query = text("""
            SELECT 
                i.*, ps.material_id,
                ps.material_description, ps.prep_date, ps.prep_operator,
                de.extract_date, de.extract_operator, de.extract_method,
                lib.library_id, lib.library_type, lib.library_operator,
                ds.fastq_name, ds.raw_reads,
                dm.endo_dna, dm.tot_reads_map
            FROM lab_data.individuals i
            LEFT JOIN lab_data.processed_samples ps ON i.lab_id = ps.lab_id
            LEFT JOIN lab_data.dna_extractions de ON i.lab_id = de.lab_id
            LEFT JOIN lab_data.libraries lib ON i.lab_id = lib.lab_id
            LEFT JOIN lab_data.dna_sequencing ds ON lib.library_id = ds.library_id
            LEFT JOIN lab_data.dna_mapping dm ON ds.fastq_name = dm.fastq_name
            WHERE i.lab_id = :id
        """)
        return pd.read_sql(query, self.engine, params={"id": lab_id})
    
    def get_project_stats(self, project_id):
        query = text("""
            SELECT 
                COUNT(DISTINCT i.lab_id) as total_individuals,
                COUNT(DISTINCT ps.material_id) as total_samples,
                COUNT(DISTINCT de.lab_id) as total_extractions,
                COUNT(DISTINCT lib.library_id) as total_libraries,
                AVG(dm.endo_dna) as avg_endogenous
            FROM lab_data.individuals i
            LEFT JOIN lab_data.processed_samples ps ON i.lab_id = ps.lab_id
            LEFT JOIN lab_data.dna_extractions de ON i.lab_id = de.lab_id
            LEFT JOIN lab_data.libraries lib ON i.lab_id = lib.lab_id
            LEFT JOIN lab_data.dna_sequencing ds ON lib.library_id = ds.library_id
            LEFT JOIN lab_data.dna_mapping dm ON ds.fastq_name = dm.fastq_name
            WHERE i.project_id = :pid
        """)
        return pd.read_sql(query, self.engine, params={"pid": project_id})

    def check_sites_from_individuals(self, dataframe, conn):
        """
        This function checks for sampling sites (parent table) information when uploading individuals (child table).
        If any new sites are present, they are added and committed to the server. 

        Input:
        - dataframe: a pandas DataFrame object (that contains a column named 'site_name');
        - conn: an established connection with the database of interest (sqlalchemy create_engine()).

        Output:
        - Pass
        """

        # Extract sampling sites names from the DataFrame
        dataframe_sampling_sites = dataframe['site_name'].unique() 

        # Extract sampling sites names from Database
        existing_sites = set(pd.read_sql("SELECT site_name FROM lab_data.sampling_sites", conn)['site_name'].tolist())

        # Flag to check for updates (default: False)
        new_sites_added = False
        
        # Parses through the sites provided by the DataFrame
        for site in dataframe_sampling_sites:
            # If it is empty, skips it
            if pd.isna(site): 
                continue
            
            # If the site is not empty, but not present in the database...
            elif site not in existing_sites:
                print(f"Sampling site '{site}' not found in Sampling Sites table. Creating entry...")

                # ... adds it to the database...
                conn.execute(sqlalchemy.text("INSERT INTO lab_data.sampling_sites (site_name) VALUES (:s)"), {"s": site})
                print(f"Sampling site '{site}' added to Sampling Sites table. Country automatically set to 'Poland'. Remember to add additional information.")

                # ... and activates the flag for database updates.
                new_sites_added = True
            
            # Id the site is already in the database, skips it
            else: continue
        
        # If the flag for database updates was activated, the changes are committed to the database.
        if new_sites_added:
            conn.commit()
        
        pass


    def get_primary_keys(self, table_name, schema='lab_data'):
        """
        Recupera dinamicamente i nomi delle colonne che compongono 
        la Primary Key di una tabella.
        """
        inspector = inspect(self.engine)
        pk_columns = inspector.get_pk_constraint(table_name, schema)
        return pk_columns.get('constrained_columns', [])

    def safe_update_table(self, table_name, edited_df, schema='lab_data'):
        """
        Aggiorna la tabella nel database mantenendo i vincoli.
        Usa 'to_sql' con un approccio temporaneo per evitare di rompere le Foreign Keys.
        """
        if edited_df.empty:
            return True

        pk_cols = self.get_primary_keys(table_name)
        if not pk_cols:
            print(f"Error: No primary key found for table {table_name}. Cannot perform UPSERT.")
            return False

        try:
            with self.engine.begin() as conn:
                # 1. Carichiamo i dati modificati in una tabella temporanea 'staging'
                staging_name = f"temp_staging_{table_name}"
                edited_df.to_sql(staging_name, conn, schema=schema, 
                                if_exists='replace', index = False)
                
                # 2. Eseguiamo un comando SQL per aggiornare la tabella originale dalla staging
                # Nota: Questo esempio presuppone che la prima colonna sia la chiave primaria (es. lab_id)
                
                columns_to_update = [col for col in edited_df.columns if col not in pk_cols]
                
                col_names = ", ".join(edited_df.columns)
                pk_constraint = ", ".join(pk_cols)
                
                # Creiamo una lista di colonne per il SELECT facendo il cast automatico
                # Se la colonna contiene "date", forziamo il tipo DATE
                select_parts = []

                for col in edited_df.columns:
                    c_low = col.lower()
                    # Se è una data vera (es. collection_date, extraction_date)
                    if "date" in c_low and "ce_" not in c_low and "epoch" not in c_low:
                        select_parts.append(f"NULLIF({col}::TEXT, '')::DATE AS {col}")
                    # Se è un anno/numero (es. date_ce_start, period_order)
                    elif "ce_" in c_low or "order" in c_low:
                        select_parts.append(f"NULLIF({col}::TEXT, '')::INTEGER AS {col}")
                    else:
                        select_parts.append(col)
                select_clause = ", ".join(select_parts)

                if not columns_to_update:
                    upsert_query = f"""
                        INSERT INTO lab_data.{table_name} ({col_names})
                        SELECT {select_clause} FROM lab_data.{staging_name}
                        ON CONFLICT ({pk_constraint}) DO NOTHING;
                    """
                else:
                    # 1. Costruiamo la lista delle assegnazioni
                    set_parts = []
                    for col in columns_to_update:
                        c_low = col.lower()
                        # CAST per DATE vere
                        if "date" in c_low and "ce_" not in c_low and "epoch" not in c_low:
                            set_parts.append(f"{col} = EXCLUDED.{col}::TEXT::DATE")
                        # CAST per ANNI/INTERI
                        elif "ce_" in c_low or "order" in c_low:
                            set_parts.append(f"{col} = EXCLUDED.{col}::TEXT::INTEGER")
                        # TESTO SEMPLICE (come Bronze Age)
                        else:
                            set_parts.append(f"{col} = EXCLUDED.{col}")
                    
                    # 2. Trasformiamo la lista in una stringa separata da virgole
                    set_clause_sql = ", ".join(set_parts)
                    
                    # 3. Componiamo la query
                    upsert_query = f"""
                        INSERT INTO lab_data.{table_name} ({col_names})
                        SELECT {select_clause} FROM lab_data.{staging_name}
                        ON CONFLICT ({pk_constraint}) 
                        DO UPDATE SET {set_clause_sql};
                    """
                
                conn.execute(text(upsert_query))

                conn.execute(text(f"DROP TABLE lab_data.{staging_name}"))
                
            return True
        except Exception as e:
            print(f"Database Error: {e}")
            return False


    def upload_from_excel(self, xlsx_path):
        """
        This function uploads on the database the information provided through an Excel File.

        Input:
        - xlsx_path: Excel file or path to it

        Ouput:
        - Pass
        """
        # Parse full Excel file
        excel_file = pd.ExcelFile(xlsx_path)
        # Recover the sheets names (stores them in a list)
        sheets = excel_file.sheet_names

        failed_sheets = []

        # Default Values
        default_values = {
            'country': 'Poland',
            'extract_method': 'Rohland et al. 2018',
            'lysis_method': 'Rohland et al. 2018', 
            'library_type': 'Single',
            'index_method': 'Cx, XX ul',
            'qPCR_method': 'AA Biotech',
            'shotgun_enriched': 'No',
            'merged': 'No'
            }

        # Opens connection to the database
        with self.engine.connect() as conn:
            
            # Parses each sheet of the Excel file
            for sheet in sheets:
                try:
                    print(f"--- Processing sheet: {sheet} ---\n")
                    # Creates a DataFrame for each sheet
                    data = pd.read_excel(xlsx_path, sheet_name = sheet)

                    if data.empty:
                        continue

                    # Lower case for column names (they already are, but just in case)
                    data.columns = [c.lower() for c in data.columns]

                    # Drop columns fully empty 
                    data = data.dropna(axis = 1, how = 'all')

                    # Convert remaining NaN in None
                    data = data.where(pd.notnull(data), None)

                    # Checks if in the database there is a Table with the same name as the sheet name
                    if self.engine.dialect.has_table(conn, sheet, schema = 'lab_data'):
                        # If yes, tries to append the new data
                        try:
                            # SAFE CHECKS FOR MISSING SAMPLING SITES
                            if sheet == "individuals":
                                self.check_sites_from_individuals(data, conn)

                            print(f"Attempting to insert {len(data)} rows into {sheet}...")

                            for col, val in default_values.items():
                                if col in data.columns:
                                    data[col] = data[col].fillna(val)
                            
                            success = self.safe_update_table(sheet, data)

                            if not success:
                                failed_sheets.append(sheet)
                            else:
                                conn.commit()
                                print(f"Table {sheet} updated correctly\n")
                        
                        except Exception as ex:
                            conn.rollback()
                            print(f"Error during upload of table {sheet}: {ex}.\n")
                            failed_sheets.append(f"{sheet} (not in DB)")
                    else:
                        print(f"Error: Database {self.db_name} has no table called '{sheet}'.")
                
                except Exception as e:
                    print(f"Critical error on sheet {sheet}: {e}")
                    failed_sheets.append(sheet)

        if failed_sheets:
            raise Exception(f"Upload failed or partial. Errors in sheets: {', '.join(failed_sheets)}")
        print(f"Upload completed!")
        return True
  

    def _rotate_backups(self, extension, max_backups = 3):
        '''
        This function deletes the oldest backup file if the number of backup files exceedes a certain amount.

        Input:
        - extension: the file extension (example, but not limited to: .xlsx, .tsv, .csv...)
        - max_backups: maximum number of backups allowed, after which the oldest file is deleted. DEFAULT = 3

        Output:
        - Pass
        '''

        files = sorted(glob.glob(f"./backups/*{extension}"), key = os.path.getmtime)

        while len(files) > max_backups:
            old_file = files.pop(0)
            os.remove(old_file)
            print(f"Old backup removed: {old_file}")
        
        pass

    def get_tables_names(self):
        """
        Obtain tables names from the database.

        Input: 
        - None

        Output:
        - a list of tables names.
        """

        inspector = inspect(self.engine)
        tables = [x for x in inspector.get_table_names(schema = 'lab_data')]
        
        return tables


    def run_backup(self):
        """Executes the backup of the .sql, .tsv and .xlsx files.
        
        Input:
        - None
        
        Ouput:
        - Pass
        """
        

        # Obtain current timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        os.makedirs("./backups", exist_ok = True)
        
        ### 1. Backup SQL
        sql_file = f"./backups/db_full_backup_{timestamp}.sql"

        # Find postgre path
        pg_dump_path = shutil.which("pg_dump")

        # If it finds it...
        if pg_dump_path:
            env = os.environ.copy()
            env["PGPASSWORD"] = self.password

            try:
                subprocess.run(
                    ["pg_dump", "-h", self.host, "-U", self.user, "-d", self.db_name, "-f", sql_file],
                    env = env, check = True)
                print(f"Created backup SQL: {sql_file}")

            except Exception as e:
                print(f"Error during the creation of the backup: {e}")
        else:
            print(f"Error: 'pg_dump' not found on the server. Skipping the .sql backup. (The database will be saved on an Excel file you can upload)")

        # 2. Export View TSV
        tsv_file = f"./backups/view_report_{timestamp}.tsv"
        df = pd.read_sql("SELECT * FROM lab_data.individuals_status", self.engine)
        df.to_csv(tsv_file, sep = '\t', index = False)
        print(f"Created report tsv: {tsv_file}")

        # 3. Export Excel
        excel_file = f"./backups/full_lab_backup_{timestamp}.xlsx"

        tables = self.get_tables_names()
        with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
            for table_name in tables:
                # Leggiamo la tabella dal DB
                df = pd.read_sql(f"SELECT * FROM lab_data.{table_name}", self.engine)
                # La scriviamo in un foglio dedicato
                df.to_excel(writer, sheet_name = table_name, index = False)
        
        print(f"Created backup Excel: {excel_file}")

        # 3. Rotation (only keeps the 3 most recent backups)
        self._rotate_backups(".sql")
        self._rotate_backups(".tsv")
        self._rotate_backups(".xlsx")

        pass


if __name__ == "__main__":
    try:
        db = LabDatabase()
        print(f"Connection to the {db.host} for user {db.user} created successfully.")
    except Exception as ex:
        print(f"Connection could not be created due to the following error:\n", ex)
