import os
import pandas as pd
from sqlalchemy import create_engine, event, inspect, text
import sqlalchemy
from collections import deque
import subprocess               # For the backup system
import shutil
import glob
from datetime import datetime
import json
from pathlib import Path



class LabDatabase:
    def __init__(self, user, password):
        config_path = Path(__file__).resolve().parent.parent / 'config.json'

        with open(config_path, 'r', encoding = 'utf-8') as f:
            self.config = json.load(f)

        self.db_name = self.config["database"]["db_name"]
        self.host = self.config["database"]["host"]
        self.port = self.config["database"]["port"]
        self.schema = self.config["database"]["schema"]  #  atm supports the presence of only one schema per db

        if user and password:
            self.url = f"postgresql://{user}:{password}@{self.host}:{self.port}/{self.db_name}"
            self.engine = create_engine(self.url)

    def get_column_values(self, table, schema = None, columns='all'):
        if schema is None:
            schema = self.schema 
        
        with self.engine.connect() as conn:
            try:
                if columns == 'all':
                    result = pd.read_sql(f"SELECT * FROM {schema}.{table}", conn)
                    return result
                
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
            
    def _build_join_graph(self):
        """
        Build a graph of table relationships based on foreign keys.
        Returns a dictionary where keys are table names and values are lists of tuples.
        """

        # Inspector retrieves metadata from the database.
        inspector = inspect(self.engine)

        graph = {}

        # For each table name obtained through the metadata...
        for table_name in inspector.get_table_names(schema=self.schema):
            # ... add the table name to the graph dictionary and set an empty list as its value
            graph.setdefault(table_name, [])

            # For each foreign key in that table...
            for fk in inspector.get_foreign_keys(table_name, schema=self.schema):

                source_table = table_name
                target_table = fk['referred_table']
                source_columns = fk.get('constrained_columns', [])
                target_columns = fk.get('referred_columns', [])

                if not source_columns or not target_columns:
                    continue

                graph.setdefault(target_table, [])

                graph[source_table].append((target_table, source_columns, target_columns))
                graph[target_table].append((source_table, target_columns, source_columns))

        return graph

    def _find_join_path(self, graph, start, target):
        """ This function finds the shortest path between two tables in the join graph. """

        # CASE 1: If the start and target are the same, return an empty path
        if start == target:
            return []

        # This library helps to implement a queue for the breadth-first search (BFS) algorithm which is used to find the shortest paths in graphs
        queue = deque([(start,[])])
        visited = {start}

        # If a queue exists...
        while queue:
            # We remove the next item, which we call "current", in front of the queue
            current, path = queue.popleft()

            # Then we continue searching: each time we visit a table we add it in the queue and visited
            for next, left_cols, right_cols in graph.get(current, []):

                # If a table was already visited, we skip it to avoid cycles in the graph
                if next in visited:
                    continue

                new_path = path + [(next, left_cols, right_cols)]

                # CASE 2: If the next table is the target, we return the path we have built so far
                if next == target:
                    return new_path

                queue.append((next, new_path))
                visited.add(next)

        # CASE 3: If we finish the search and we haven't found the target, we return None
        return None

    def _build_sample_details_query(self):
        mapping = self.config["database"]["mapping"]

        # We use individual_id as the base column for the query (we use .get to avoid crashing)
        base_entry = mapping.get("individual_id", {})

        # The base table will be the one where to start the JOIN chain
        base_table = base_entry.get("base_table")
        base_key_col = base_entry.get("column_name")

        if not any([base_table, base_key_col]):
            raise ValueError("mapping['individual_id'] information is required. Please check config.json.")

        graph = self._build_join_graph()

        # Here we initialize the SELECT and JOIN parts of the SQL query
        select_parts = []
        join_parts = []

        # Here we create a set of JOINs to monitor because we don't want to duplicate them
        seen_joins = set()

        # The value 'base' here will be defined at the end of the query
        select_parts.append(f"base.{base_key_col} AS individual_id")

        requested_fields = [
            "site_name",
            "material_id",
            "prep_date",
            "extract_date",
            "library_id",
            "raw_reads",
            "endo_dna",
            "tot_reads_map"
        ]

        # add all mapped fields
        for concept, info in mapping.items():
            if concept in requested_fields:
                print(f"Getting field: {concept}")
                target_table = info.get("base_table")
                print(f"Its table is: {base_table}")
                target_column = info.get("column_name")
                print(f"Its column is: {target_column}")

                # CASE 1: If the target table or column is not defined, we skip this field
                if not target_table or not target_column:
                    continue

                # CASE 2: If the target table is the same as the base table, we can directly select the column without any JOIN
                if target_table == base_table:
                    select_parts.append(f"base.{target_column} AS {concept}")
                    continue

                # CASE 3: If the target table is different from the base table, we need to find a JOIN path 
                path = self._find_join_path(graph, base_table, target_table)

                if path is None:
                    raise ValueError(f"No join path found between {base_table} and {target_table}")

                # the current alias is what we call the base table in the query to which we attach all the JOINs.
                current_alias = "base"
                # The current table is instead the one we are currently visiting in the JOIN path.
                current_table = base_table

                for next_table, left_cols, right_cols in path:
                    if not left_cols or not right_cols:
                        continue

                    # Here we create a tuple that represents the JOIN between the current table and the next in the graph
                    # We do this to avoid duplicating JOINs in the SQL query, which would cause errors.
                    join_key = (current_table, next_table)
                    if join_key not in seen_joins:
                        join_conditions = []
                        for left_col, right_col in zip(left_cols, right_cols):
                            # This is the condition for the JOIN: which columns are we joining?
                            join_conditions.append(
                                f"{current_alias}.{left_col} = {next_table}.{right_col}"
                            )

                        # And then now that we have the name of the table, and the condition for the JOIN
                        # we create the JOIN line itself
                        join_parts.append(
                            f"LEFT JOIN {self.schema}.{next_table} AS {next_table} "
                            f"ON {' AND '.join(join_conditions)}"
                        )

                        # And here we add the JOIN to the set seen before, so we do not create it again >_>
                        seen_joins.add(join_key)

                    # We update the alias and table to continue the JOIN chain
                    current_alias = next_table
                    current_table = next_table

                # So we add the final SELECT part for this concept, which is now reachable through the JOINs we have built
                select_parts.append(f"{target_table}.{target_column} AS {concept}")

            # The final SQL query is built by joining the SELECT parts and the JOIN parts, and adding a WHERE clause to filter by the individual_id
            sql = f"""
                SELECT
                    {', '.join(select_parts)}
                FROM {self.schema}.{base_table} AS base
                {' '.join(join_parts)}
                WHERE base.{base_key_col} = :individual_id
            """

        return text(sql)

    def get_sample_details(self, individual_id):
        query = self._build_sample_details_query()
        return pd.read_sql(query, self.engine, params={"individual_id": individual_id})


    def _build_long_sample_details_query(self):
        mapping = self.config["database"]["mapping"]

        # We use individual_id as the base column for the query (we use .get to avoid crashing)
        base_entry = mapping.get("individual_id", {})

        # The base table will be the one where to start the JOIN chain
        base_table = base_entry.get("base_table")
        base_key_col = base_entry.get("column_name")

        if not any([base_table, base_key_col]):
            raise ValueError("mapping['individual_id'] information is required. Please check config.json.")

        graph = self._build_join_graph()

        # Here we initialize the SELECT and JOIN parts of the SQL query
        select_parts = []
        join_parts = []

        # Here we create a set of JOINs to monitor because we don't want to duplicate them
        seen_joins = set()

        

        # add all mapped fields
        for concept, info in mapping.items():
            target_table = info.get("base_table")
            target_column = info.get("column_name")

            # CASE 1: If the target table or column is not defined, we skip this field
            if not target_table or not target_column:
                continue

            # CASE 2: If the target table is the same as the base table, we can directly select the column without any JOIN
            if target_table == base_table:
                select_parts.append(f"base.{target_column} AS {concept}")
                continue

            # CASE 3: If the target table is different from the base table, we need to find a JOIN path 
            path = self._find_join_path(graph, base_table, target_table)

            if path is None:
                raise ValueError(f"No join path found between {base_table} and {target_table}")

            # the current alias is what we call the base table in the query to which we attach all the JOINs.
            current_alias = "base"
            # The current table is instead the one we are currently visiting in the JOIN path.
            current_table = base_table

            for next_table, left_cols, right_cols in path:
                if not left_cols or not right_cols:
                    continue

                # Here we create a tuple that represents the JOIN between the current table and the next in the graph
                # We do this to avoid duplicating JOINs in the SQL query, which would cause errors.
                join_key = (current_table, next_table)
                if join_key not in seen_joins:
                    join_conditions = []
                    for left_col, right_col in zip(left_cols, right_cols):
                        # This is the condition for the JOIN: which columns are we joining?
                        join_conditions.append(
                            f"{current_alias}.{left_col} = {next_table}.{right_col}"
                        )

                    # And then now that we have the name of the table, and the condition for the JOIN
                    # we create the JOIN line itself
                    join_parts.append(
                        f"LEFT JOIN {self.schema}.{next_table} AS {next_table} "
                        f"ON {' AND '.join(join_conditions)}"
                    )

                    # And here we add the JOIN to the set seen before, so we do not create it again >_>
                    seen_joins.add(join_key)

                # We update the alias and table to continue the JOIN chain
                current_alias = next_table
                current_table = next_table

            # So we add the final SELECT part for this concept, which is now reachable through the JOINs we have built
            select_parts.append(f"{target_table}.{target_column} AS {concept}")

        # The final SQL query is built by joining the SELECT parts and the JOIN parts, and adding a WHERE clause to filter by the individual_id
        sql = f"""
            SELECT
                {', '.join(select_parts)}
            FROM {self.schema}.{base_table} AS base
            {' '.join(join_parts)}
            WHERE base.{base_key_col} = :individual_id
        """

        return text(sql)

    def get_long_sample_details(self, individual_id):
        query = self._build_long_sample_details_query()
        return pd.read_sql(query, self.engine, params={"individual_id": individual_id})
    
    def _build_project_details_query(self):
        mapping = self.config["database"]["mapping"]

        base_entry = mapping.get("individual_id", {})
        base_table = base_entry.get("base_table")
        base_key_col = base_entry.get("column_name")

        # Define a filter 
        project_col = mapping.get("project_id", {}).get("column_name", "project_id")

        if not any([base_table, base_key_col]):
            raise ValueError("mapping['individual_id'] information is required. Please check config.json.")
        
        graph = self._build_join_graph()

        requested_fields = {
            "individual_id" : ["total_individuals", "COUNT(DISTINCT)"],
            "material_id" : ["total_samples", "COUNT(DISTINCT)"],
            "library_id" : ["total_libraries", "COUNT(DISTINCT)"],
            "endo_dna" : ["avg_endo_dna", "AVG"]
        }

        # Here we initialize the SELECT and JOIN parts of the SQL query
        select_parts = []
        join_parts = []
        
        # Here we create a set of JOINs to monitor because we don't want to duplicate them
        seen_joins = set()

        for concept, info in mapping.items():
            if concept in requested_fields.keys():
                target_table = info.get("base_table")
                target_column = info.get("column_name")

                if not target_table or not target_column:
                    continue

                if target_table == base_table:
                    if "DISTINCT" in requested_fields[concept][1]:
                        select_parts.append(f"COUNT(DISTINCT base.{target_column}) AS {requested_fields[concept][0]}")
                        continue
                    elif "AVG" in requested_fields[concept][1]:
                        select_parts.append(f"AVG(base.{target_column}) AS {requested_fields[concept][0]}")
                        continue

                path = self._find_join_path(graph, base_table, target_table)

                if path is None:
                    raise ValueError(f"No join path found between {base_table} and {target_table}")

                current_alias = "base"
                current_table = base_table

                for next_table, left_cols, right_cols in path:
                    if not left_cols or not right_cols:
                        continue

                    join_key = (current_table, next_table)
                    if join_key not in seen_joins:
                        join_conditions = []
                        for left_col, right_col in zip(left_cols, right_cols):
                            join_conditions.append(
                                f"{current_alias}.{left_col} = {next_table}.{right_col}"
                            )

                        join_parts.append(
                            f"LEFT JOIN {self.schema}.{next_table} AS {next_table} "
                            f"ON {' AND '.join(join_conditions)}"  
                        )

                        seen_joins.add(join_key)

                    current_alias = next_table
                    current_table = next_table

                if "DISTINCT" in requested_fields[concept][1]:
                    select_parts.append(f"COUNT(DISTINCT {target_table}.{target_column}) AS {requested_fields[concept][0]}")
                elif "AVG" in requested_fields[concept][1]:
                    select_parts.append(f"AVG({target_table}.{target_column}) AS {requested_fields[concept][0]}")

        sql = f"""
            SELECT
                {', '.join(select_parts)}
            FROM {self.schema}.{base_table} AS base
            {' '.join(join_parts)}
            WHERE base.{project_col} = :project_id
        """
        return text(sql)

    def get_project_details(self, project_id):
        query = self._build_project_details_query()
        return pd.read_sql(query, self.engine, params={"project_id": project_id})

    def get_primary_keys(self, table_name, schema=None):
        """
        Recover the primary keys of a table in the database.
        """
        if schema is None:
            schema = self.schema 

        inspector = inspect(self.engine)
        pk_columns = inspector.get_pk_constraint(table_name, schema)
        return pk_columns.get('constrained_columns', [])

    def check_parent_from_child(self, parent_name, child_dataframe, conn, schema=None):
        """
        This function checks for parent table information when uploading child table information.
        If any new rows are present, they are added and committed to the server.

        Input:
        - parent_name: name of the parent table;
        - child_datframe: a pandas DataFrame object with child table information;
        - conn: an established connection with the database of interest (sqlalchemy create_engine());
        - schema: name of the schema that contains the tables.

        Output:
        - Pass
        """
        if schema is None:
            schema = self.schema 
        # 1. Recupera i nomi delle colonne della Primary Key del parent
        pk_columns = self.get_primary_keys(parent_name, schema)
        if not pk_columns:
            print(f"Error: No primary key found for: {parent_name}")
            return

        # 2. Remove duplicates from child info
        child_entries = child_dataframe[pk_columns].drop_duplicates().dropna()

        # Get information from parent child, only primary keys columns.
        cols_str = ", ".join(pk_columns)
        existing_parent_data = pd.read_sql(f"SELECT {cols_str} FROM {schema}.{parent_name}", conn)

        # Convert data in tuples sets. If there is only one Primary key, the tuple is of format (val,)
        existing_set = set(tuple(x) for x in existing_parent_data.to_records(index=False))

        new_rows_added = False

        # For loop to each row of the new child dataframe
        for _, row in child_entries.iterrows():
            current_entry = tuple(row[col] for col in pk_columns)

            if current_entry not in existing_set:
                print(f"Entry {current_entry} not found in parent table '{parent_name}'. Creating entry...")

                # Building the query
                placeholders = ", ".join([f":{col}" for col in pk_columns])
                insert_sql = f"INSERT INTO {schema}.{parent_name} ({cols_str}) VALUES ({placeholders})"
                
                params = {col: row[col] for col in pk_columns}
                conn.execute(sqlalchemy.text(insert_sql), params)
                new_rows_added = True

        # 6. Final commit if there is any change in the dataset
        if new_rows_added:
            conn.commit()
            print(f"Updated the database on table '{parent_name}'. Please remember to check later the newly added information.")
        else:
            print(f"No new row for table '{parent_name}'.")
        


    def safe_update_table(self, table_name, edited_df, schema=None):
        """
        Updates table taking into consideration the primary keys of the table. 
        If a row with the same primary key exists, it will be updated; otherwise, it will be inserted.
        """
        if schema is None:
            schema = self.schema 

        if edited_df.empty:
            return True

        pk_cols = self.get_primary_keys(table_name)
        if not pk_cols:
            print(f"Error: No primary key found for table {table_name}. Cannot perform UPSERT.")
            return False

        try:
            with self.engine.begin() as conn:
                # Temporary staging table name
                staging_name = f"temp_staging_{table_name}"
                edited_df.to_sql(staging_name, conn, schema=schema, 
                                if_exists='replace', index = False)
                
                # 2. Eseguiamo un comando SQL per aggiornare la tabella originale dalla staging
                # Nota: Questo esempio presuppone che la prima colonna sia la chiave primaria (es. lab_id)
                
                columns_to_update = [col for col in edited_df.columns if col not in pk_cols]
                
                col_names = ", ".join(edited_df.columns)
                pk_constraint = ", ".join(pk_cols)

                inspector = inspect(self.engine)
                database_cols = inspector.get_columns(table_name, schema=schema)
                # Creiamo una lista di colonne per il SELECT facendo il cast automatico
                # Se la colonna contiene "date", forziamo il tipo DATE
                select_parts = []

                for col in edited_df.columns:
                    col_info = next((database_col for database_col in database_cols if database_col['name'].lower() == col.lower()), None)
                    col_type = str(col_info['type']).lower() if col_info else None

                    if "date" in col_type or "timestamp" in col_type:
                        select_parts.append(f"NULLIF({col}::TEXT, '')::DATE AS {col}")
                    elif "integer" in col_type or "int" in col_type:
                        select_parts.append(f"NULLIF({col}::TEXT, '')::INTEGER AS {col}")
                    elif "numeric" in col_type or "float" in col_type or "double" in col_type:
                        select_parts.append(f"NULLIF({col}::TEXT, '')::NUMERIC AS {col}")
                    elif "bool" in col_type or "boolean" in col_type:
                        select_parts.append(f"NULLIF({col}::TEXT, '')::BOOLEAN AS {col}")
                    else:
                        select_parts.append(col)

                select_clause = ", ".join(select_parts)

                if not columns_to_update:
                    upsert_query = f"""
                        INSERT INTO {schema}.{table_name} ({col_names})
                        SELECT {select_clause} FROM {schema}.{staging_name}
                        ON CONFLICT ({pk_constraint}) DO NOTHING;
                    """
                else:
                    # 1. Costruiamo la lista delle assegnazioni
                    set_parts = []
                    for col in columns_to_update:
                        col_info = next(
                            (database_col for database_col in database_cols if database_col["name"].lower() == col.lower()),
                            None
                        )
                        col_type = str(col_info["type"]).lower() if col_info else None

                        if "date" in col_type or "timestamp" in col_type:
                            set_parts.append(f"{col} = EXCLUDED.{col}::TEXT::DATE")
                        elif "integer" in col_type or "int" in col_type:
                            set_parts.append(f"{col} = EXCLUDED.{col}::TEXT::INTEGER")
                        elif "numeric" in col_type or "float" in col_type or "double" in col_type:
                            set_parts.append(f"{col} = EXCLUDED.{col}::TEXT::NUMERIC")
                        elif "bool" in col_type or "boolean" in col_type:
                            set_parts.append(f"{col} = EXCLUDED.{col}::TEXT::BOOLEAN")
                        else:
                            set_parts.append(f"{col} = EXCLUDED.{col}")
                    
                    # 2. Trasformiamo la lista in una stringa separata da virgole
                    set_clause_sql = ", ".join(set_parts)
                    
                    # 3. Componiamo la query
                    upsert_query = f"""
                        INSERT INTO {schema}.{table_name} ({col_names})
                        SELECT {select_clause} FROM {schema}.{staging_name}
                        ON CONFLICT ({pk_constraint}) 
                        DO UPDATE SET {set_clause_sql};
                    """
                
                conn.execute(text(upsert_query))

                conn.execute(text(f"DROP TABLE {schema}.{staging_name}"))
                
            return True
        except Exception as e:
            print(f"Database Error: {e}")
            return False


    def _get_parent_for_sheet(self, sheet_name):
        """Return the parent table for a sheet if a hierarchy entry exists."""
        table_hierarchies = self.config.get("database", {}).get("table_hierarchies", {})
        sheet_config = table_hierarchies.get(sheet_name, {})
        return sheet_config.get("parent")

    def upload_from_excel(self, xlsx_path, schema=None):
        """
        This function uploads on the database the information provided through an Excel File.

        Input:
        - xlsx_path: Excel file or path to it

        Ouput:
        - Pass
        """
        if schema is None:
            schema = self.schema
            
        # Parse full Excel file
        excel_file = pd.ExcelFile(xlsx_path)
        # Recover the sheets names (stores them in a list)
        sheets = excel_file.sheet_names

        failed_sheets = []

        # Default Values
        default_values = self.config["database"]["default_values"]

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
                    if self.engine.dialect.has_table(conn, sheet, schema = schema):
                        # If yes, tries to append the new data
                        try:
                            
                            parent_name = self._get_parent_for_sheet(sheet)
                            if parent_name:
                                self.check_parent_from_child(parent_name=parent_name, child_dataframe=data, conn=conn)

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
            try:
                os.remove(old_file)
                print(f"Old backup removed: {old_file}")
            except Exception as e:
                print(f"Error while removing old backup {old_file}: {e}")

        pass

    def get_tables_names(self, schema = None):
        """
        Obtain tables names from the database.

        Input: 
        - None

        Output:
        - a list of tables names.
        """
        if schema is None:
            schema = self.schema

        inspector = inspect(self.engine)

        tables = [x for x in inspector.get_table_names(schema = schema)]
        
        return tables


    def run_backup(self, schema = None):
        """Executes the backup of the .tsv and .xlsx files.
        
        Input:
        - None
        
        Ouput:
        - Pass
        """
        if schema == None:
            schema = self.schema

        # 1. Obtain current timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        os.makedirs("./backups", exist_ok = True)
        
        # 2. Export View TSV
        tsv_file = f"./backups/view_report_{timestamp}.tsv"
        all_individual_ids = self.get_column_values(
            table=self.config["database"]["mapping"]["individual_id"]["base_table"],
            columns=self.config["database"]["mapping"]["individual_id"]["column_name"],
        )
        requested_fields = [
            "individual_id",
            "site_name",
            "material_id",
            "prep_date",
            "extract_date",
            "library_id",
            "raw_reads",
            "endo_dna",
            "tot_reads_map"
        ]

        details_frames = []
        for individual_id in all_individual_ids:
            df = self.get_sample_details(individual_id)
            if df.empty:
                continue

            if "individual_id" not in df.columns:
                df = df.copy()
                df["individual_id"] = individual_id

            df = df.reindex(columns=requested_fields, fill_value=pd.NA)
            details_frames.append(df)

        if details_frames:
            combined_df = pd.concat(details_frames, ignore_index=True)
            combined_df.to_csv(tsv_file, sep='\t', index=False)
        else:
            pd.DataFrame(columns=requested_fields).to_csv(tsv_file, sep='\t', index=False)

        print(f"Created report tsv: {tsv_file}")

        # 3. Export Excel
        excel_file = f"./backups/full_lab_backup_{timestamp}.xlsx"

        tables = self.get_tables_names()
        with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
            for table_name in tables:
                # Leggiamo la tabella dal DB
                df = pd.read_sql(f"SELECT * FROM {schema}.{table_name}", self.engine)
                # La scriviamo in un foglio dedicato
                df.to_excel(writer, sheet_name = table_name, index = False)
        
        print(f"Created backup Excel: {excel_file}")

        # 3. Rotation (only keeps the 3 most recent backups)
        self._rotate_backups(".tsv")
        self._rotate_backups(".xlsx")

        pass


if __name__ == "__main__":
    try:
        user = input("User: ")
        password = input("Password: ")
        db = LabDatabase(user=user, password=password)
        print(f"Connection to the {db.host} for user {db.user} created successfully.")
    except Exception as ex:
        print(f"Connection could not be created due to the following error:\n", ex)
