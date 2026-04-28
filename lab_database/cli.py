import argparse
import sys
from lab_database.commands import web_interface, parse_folder, eager_helper

def main():
    parser = argparse.ArgumentParser(
        prog = "mytool", 
        description = "Paleogenetics and Conservation Genetics Lab Management Tool"
    )
    
    # Global commands
    parser.add_argument("--dry-run", action = "store_true", help = "Do not update database, only show what would happen")
    subparsers = parser.add_subparsers(dest = "command", help = "Available commands")

    # Command for web_interface
    web_interface.add_parser(subparsers)
    
    # Command for parsing folders
    parse_folder.add_parser(subparsers)

    # Command for eager
    eager_helper.add_parser(subparsers)

    args = parser.parse_args()

    # Only runs if the user gives some commands
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()  