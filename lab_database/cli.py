import subprocess
import sys
import os

def run(args):
    # Trova il percorso del file interface.py (o quello che l'interfaccia)
    # Assumendo che sia dentro il pacchetto
    interface_path = os.path.join(os.path.dirname(__file__), "..", "interface.py")
    
    print(f"Starting Anthill Interface from {interface_path}...")
    try:
        # Esegue: streamlit run path/to/interface.py
        subprocess.run(["streamlit", "run", interface_path], check=True)
    except KeyboardInterrupt:
        print("\nStopping server...")