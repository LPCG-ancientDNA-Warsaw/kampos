import os
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy import event
import sqlalchemy
from dotenv import load_dotenv  # Can read the .env file
import subprocess               # For the backup system
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

    def check_sites_from_individuals(self, dataframe):
        with self.engine.connect() as conn:
            dataframe_sampling_sites = dataframe['site_name'].unique()

            existing_sites_database = pd.read_sql("SELECT site_name FROM lab_data.sampling_sites", conn)
            existing_sites = existing_sites_database['site_name'].tolist()

            new_sites_added = False
            
            for site in dataframe_sampling_sites:
                if pd.isna(site): 
                    continue

                elif site not in existing_sites:
                    print(f"Sampling site '{site}' not found in Sampling Sites table. Creating entry...")
                    conn.execute(sqlalchemy.text("INSERT INTO lab_data.sampling_sites (site_name) VALUES (:s)"), {"s": site})
                    print(f"Sampling site '{site}' added to Sampling Sites table. Country automatically set to 'Poland'. Remember to add additional information.")
                    new_sites_added = True
                
                else: continue
                
            if new_sites_added:
                conn.commit()


    def upload_from_excel(self, xlsx_path):
        # Parse full Excel file
        excel_file = pd.ExcelFile(xlsx_path)
        # Recover the sheets names (stores them in a list)
        sheets = excel_file.sheet_names

        with self.engine.connect() as conn:
            # Parses each sheet of the Excel file
            for sheet in sheets:
                # Creates a DataFrame for each sheet
                data = pd.read_excel(xlsx_path, sheet_name = sheet)
                data = data.where(pd.notnull(data), None)

                # Checks if in the database there is a Table with the same name as the sheet name
                if self.engine.dialect.has_table(conn, sheet, schema = 'lab_data'):
                    # If yes, tries to append the new data
                    try:
                        # SAFE CHECKS FOR MISSING SAMPLING SITES
                        if sheet == "individuals":
                            self.check_sites_from_individuals(data)

                        data.to_sql(sheet, con = self.engine, schema = 'lab_data', if_exists = 'append', index = False)
                        conn.commit()

                        print(f"Table {sheet} updated correctly")
                    except Exception as ex:
                        conn.rollback()
                        print(f"Error during upload of table {sheet}")
                else:
                    print(f"Error: Database {self.db_name} has no table called '{sheet}'.")

        print(f"Upload completed!")

    def _rotate_backups(self, extension):
        files = sorted(glob.glob(f"./backups/*{extension}"), key = os.path.getmtime)
        
        while len(files) > 3:
            old_file = files.pop(0)
            os.remove(old_file)
            print(f"Old backup removed: {old_file}")

    def run_backup(self):
        """Executes the backup of the SQL file and exports the view "Individuals status"."""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        os.makedirs("./backups", exist_ok = True)
        
        # 1. Backup SQL
        sql_file = f"./backups/db_full_backup_{timestamp}.sql"
        env = os.environ.copy()
        env["PGPASSWORD"] = self.password

        try:
            subprocess.run(
                ["pg_dump", "-h", self.host, "-U", self.user, "-d", self.db_name, "-f", sql_file],
                env = env, check = True
            )
            print(f"Created backup SQL: {sql_file}")

        except Exception as e:
            print(f"Error during the creation of the backup: {e}")

        # 2. Export View CSV
        csv_file = f"./backups/view_report_{timestamp}.csv"
        df = pd.read_sql("SELECT * FROM lab_data.individuals_status", self.engine)
        df.to_csv(csv_file, index=False)
        print(f"CSV report on Individuals status created: {csv_file}")

        # 3. Rotation (only keeps the 3 most recent backups)
        self._rotate_backups(".sql")
        self._rotate_backups(".csv")


    def export_full_excel_backup(self):
        """Esporta l'intero database in un unico file Excel con più fogli."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        excel_file = f"./backups/full_lab_backup_{timestamp}.xlsx"
        
        # Elenco delle tabelle che vogliamo esportare
        tables = ['sampling_sites', 'individuals', 'sequencing_libraries', 'dna_sequencing']
        
        # Usiamo ExcelWriter di Pandas per gestire più fogli
        with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
            for table_name in tables:
                # Leggiamo la tabella dal DB
                df = pd.read_sql(f"SELECT * FROM lab_data.{table_name}", self.engine)
                # La scriviamo in un foglio dedicato
                df.to_excel(writer, sheet_name=table_name, index=False)
        
        self._rotate_backups(".xlsx")
        
        print(f"📊 Backup Excel multi-foglio creato: {excel_file}")

# Esempio di utilizzo
if __name__ == "__main__":
    
    try:
        db = LabDatabase()
        print(f"Connection to the {db.host} for user {db.user} created successfully.")
    except Exception as ex:
        print(f"Connection could not be created due to the following error:\n", ex)