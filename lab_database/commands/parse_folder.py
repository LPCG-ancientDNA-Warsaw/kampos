import os
import re
import json
from lab_database.db_manager import LabDatabase

# Gestione Pysam (per evitare crash su Windows)
try:
    import pysam
except ImportError:
    pysam = None

def get_user_config(user):
    """Carica la regex dell'utente dal file JSON."""
    # Assumiamo che il file sia nella stessa cartella del tool
    config_path = os.path.join(os.path.dirname(__file__), "..", "users_config.json")
    try:
        with open(config_path, 'r') as f:
            configs = json.load(f)
        return configs.get(user, {}).get("regex")
    except FileNotFoundError:
        return None

def extract_id(filename, pattern):
    """Usa la regex per estrarre il Lab ID dal nome del file."""
    if not pattern:
        return None
    match = re.search(pattern, filename)
    return match.group(1) if match else None

# ... (import e funzioni extract_id, ecc.) ...

def add_parser(subparsers):
    # Questo aggiunge il "sottocomando" al parser principale
    parser = subparsers.add_parser("parse", help="Parse folders")
    parser.add_argument("--user", required=True)
    parser.add_argument("--fastq")
    parser.add_argument("--bam")
    parser.add_argument("--seq-id") # La flag facoltativa che dicevi!
    
    # Questo dice a cli.py: "Se l'utente scrive 'parse', esegui la funzione run che vedi qui sotto"
    parser.set_defaults(func=run)

def run(args):
    db = LabDatabase()
    user_regex = get_user_config(args.user)
    
    if not user_regex:
        print(f"Error: User '{args.user}' not found in configuration.")
        return

    results = []

    # 1. LOGICA BAM
    if args.bam:
        if pysam is None:
            print("Error: pysam not installed. Cannot parse BAM files on this OS.")
        else:
            print(f"--- Parsing BAM files in {args.bam} (User: {args.user}) ---")
            for file in os.listdir(args.bam):
                if file.endswith(".bam"):
                    lab_id = extract_id(file, user_regex)
                    if lab_id:
                        path = os.path.join(args.bam, file)
                        with pysam.AlignmentFile(path, "rb") as samfile:
                            mapped = samfile.mapped
                            total = samfile.mapped + samfile.unmapped
                        
                        print(f"BAM Found: {file} -> ID: {lab_id} (Mapped: {mapped})")
                        results.append({'lab_id': lab_id, 'mapped': mapped, 'total': total, 'type': 'bam'})

    # 2. LOGICA FASTQ (Raw Reads)
    if args.fastq:
        print(f"--- Parsing FASTQ files in {args.fastq} ---")
        for file in os.listdir(args.fastq):
            if file.endswith((".fastq.gz", ".fq.gz")):
                lab_id = extract_id(file, user_regex)
                if lab_id:
                    # Nota: contare le righe di un fastq.gz è lento in Python puro.
                    # Per ora segniamo solo che il file esiste.
                    print(f"FASTQ Found: {file} -> ID: {lab_id}")
                    results.append({'lab_id': lab_id, 'file_name': file, 'type': 'fastq'})

    # 3. LOGICA DRY RUN / UPDATE
    if not results:
        print("No matching files found.")
        return

    if args.dry_run:
        print("\n" + "="*30)
        print("[DRY RUN] Summary of actions:")
        for r in results:
            if r['type'] == 'bam':
                print(f"- Would update BAM stats for {r['lab_id']}: {r['mapped']} mapped reads.")
            else:
                print(f"- Would link FASTQ {r['file_name']} to {r['lab_id']}.")
        print("="*30)
        print("No changes were made to the database.")
    else:
        # Qui chiameremo la funzione del DB (da creare)
        # db.update_from_parsing(results)
        print(f"\nSuccessfully processed {len(results)} files.")