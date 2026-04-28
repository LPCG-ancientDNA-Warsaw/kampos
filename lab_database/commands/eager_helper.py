

def add_parser(subparsers):
    parser = subparsers.add_parser("web", help="Launch the Streamlit web interface")
    parser.set_defaults()