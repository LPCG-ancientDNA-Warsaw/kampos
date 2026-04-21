import os
import pandas as pd
from sqlalchemy import create_engine
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

    def upload_from_excel(self, csv_path):
        df = pd.read_csv(csv_path)
        #### Still need to write it
        print(f"Upload of {len(df)} rows completed!")

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
    db = LabDatabase()
    print("Connessione stabilita con successo!")