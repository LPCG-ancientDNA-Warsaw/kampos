import subprocess
import os

def add_parser(subparsers):
    parser = subparsers.add_parser("web_interface", help="Launch the Streamlit web interface")
    parser.set_defaults(func = run)

def run(args):
    current_dir = os.path.dirname(__file__)
    app_path = os.path.join(current_dir, "..", "app_streamlit.py")
    
    print("Launching Anthill Web Interface...")
    subprocess.run(["streamlit", "run", app_path])