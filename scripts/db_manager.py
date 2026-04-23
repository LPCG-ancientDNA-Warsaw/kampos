import os
import pandas as pd
from sqlalchemy import create_engine, event, inspect
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

        # Opens connection to the database
        with self.engine.connect() as conn:
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
            
            # Parses each sheet of the Excel file
            for sheet in sheets:
                print(f"--- Processing sheet: {sheet} ---\n")
                # Creates a DataFrame for each sheet
                data = pd.read_excel(xlsx_path, sheet_name = sheet)

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
                        
                        data.to_sql(sheet, con = self.engine, schema = 'lab_data', if_exists = 'append', index = False)
                        conn.commit()

                        print(f"Table {sheet} updated correctly\n")
                    except Exception as ex:
                        conn.rollback()
                        print(f"Error during upload of table {sheet}: {ex}.\n")
                else:
                    print(f"Error: Database {self.db_name} has no table called '{sheet}'.")

        print(f"Upload completed!")
        pass




    def _rotate_backups(self, extension):
        files = sorted(glob.glob(f"./backups/*{extension}"), key = os.path.getmtime)
        
        while len(files) > 3:
            old_file = files.pop(0)
            os.remove(old_file)
            print(f"Old backup removed: {old_file}")

    def get_tables_names(self):
        inspector = inspect(self.engine)
        tables = [x for x in inspector.get_table_names(schema = 'lab_data')]
        return tables


    def run_backup(self):
        """Executes the backup of the SQL file and exports the view "Individuals status"."""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        os.makedirs("./backups", exist_ok = True)
        
        # 1. Backup SQL
        sql_file = f"./backups/db_full_backup_{timestamp}.sql"

        pg_dump_path = shutil.which("pg_dump")

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
        print(f"TSV report on Individuals status created: {tsv_file}")

        # 3. Export Excel
        excel_file = f"./backups/full_lab_backup_{timestamp}.xlsx"
        
        # Elenco delle tabelle che vogliamo esportare
        tables = self.get_tables_names()
        
        # Usiamo ExcelWriter di Pandas per gestire più fogli
        with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
            for table_name in tables:
                # Leggiamo la tabella dal DB
                df = pd.read_sql(f"SELECT * FROM lab_data.{table_name}", self.engine)
                # La scriviamo in un foglio dedicato
                df.to_excel(writer, sheet_name = table_name, index = False)
        
        print(f"📊 Backup Excel multi-foglio creato: {excel_file}")

        # 3. Rotation (only keeps the 3 most recent backups)
        self._rotate_backups(".sql")
        self._rotate_backups(".tsv")
        self._rotate_backups(".xlsx")

# Esempio di utilizzo
if __name__ == "__main__":
    
    try:
        db = LabDatabase()
        print(f"Connection to the {db.host} for user {db.user} created successfully.")
    except Exception as ex:
        print(f"Connection could not be created due to the following error:\n", ex)
