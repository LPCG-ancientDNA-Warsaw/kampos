import os
import pandas as pd
from sqlalchemy import create_engine, event, inspect, text
import sqlalchemy
import sqlite3
from collections import deque
import subprocess               # For the backup system
import glob
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import io

class LabDatabase:
    """This class defines what a Database is.
    
    Attributes:
    - .user: user name of the owner/user of the database. Required to create the object.
    - .password: password of the owner/user of the database. Required to create the object.
    - .config: a Python dictionary containing all the information from the config.json file.
    - .db_name: database name. Obtained from the config.json file.
    - .host: DB address. Obtained from the config.json file.
    - .port: connection port. Obtained from the config.json file.
    - .projects: "projects" in which the DB is divided into. Obtained from the config.json file.
    - .schemas: name of the schema for each project. Obtained from the config.json file.
    - .url: complete URL to connect to the database. Built using the information given and extracted from config.json.
    - .engine: connection established using the URL.

    Methods:
        Available:
            - get_get_column_values(table, project = None, schema = None, columns='all').
            - get_sample_details(individual_id, project=None, schema=None).
            - get_long_sample_details(individual_id, project=None, schema=None).
            - get_project_details(project_id, project=None, schema=None).
            - get_primary_keys(table_name, schema=None, project=None).
            - check_parent_from_child(parent_name, child_dataframe, conn, schema=None, project=None).
            - safe_update_table(table_name, edited_df, schema=None, project=None).
            - generate_excel_template(schema = None, project = None).
            - upload_from_excel(xlsx_path, schema=None, project=None).
            - get_tables_names(self, schema = None, project = None).
            - save_backup(target, writer, keep_existing=False).
            - write_postgresql_dump(path, schema = None, project = None).
            - write_sqlite_export(path, schema = None, project = None).
            - write_excel_export(path, schema = None, project = None).
            - run_backup(schema = None, project = None).

        Hidden:
            - _build_join_graph(project = None, schema = None).
            - _find_join_path(graph, start, target).
            - _build_sample_details_query(project = None, schema = None).
            - _build_long_sample_details_query(project = None, schema = None).
            - _build_project_details_query(project = None, schema = None).
            - _get_parent_for_sheet(sheet_name).
            - _rotate_backups(extension, schema=None, project=None, max_backups = 5)
    """

    def __init__(self, user, password):
        # Obtain the path of the file config.json
        config_path = Path(__file__).resolve().parent.parent / 'config.json'

        # Obtain information from config.json
        with open(config_path, 'r', encoding = 'utf-8') as f:
            self.config = json.load(f)

        # Initialize attributes
        self.db_name = self.config["database"]["db_name"]
        self.host = self.config["database"]["host"]
        self.port = self.config["database"]["port"]
        self.projects = [p["name"] for p in self.config["database"]["projects"]]
        self.schemas = [p["schema_name"] for p in self.config["database"]["projects"]]

        # Create the engine to establish a connection to the database
        if user and password:
            self.url = f"postgresql://{user}:{password}@{self.host}:{self.port}/{self.db_name}"
            self.engine = create_engine(self.url)

    def get_column_values(self, table, project = None, schema = None, columns='all'):
        """
        This function extracts the value of one or more columns from a specific table.
        
        Input:
        - table: the table from which to extract the column(s).
        - project: macroproject name. Optional.
        - schema: schema name. Optional.
        - columns: a string or list of columns to extract. Default: "all".
        
        Output:
        - a pandas dataframe."""

        # If a project name is given it ectracts the schema name used for it.
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            # If a project name is not provided, nor a schema name, uses the first schema available.
            else:
                schema = self.schemas[0]

        # Establish a connection with the database.
        with self.engine.connect() as conn:
            try:
                # If all columns are requested, the function returns the whole table as a Pandas dataframe
                if columns == 'all':
                    result = pd.read_sql(f"SELECT * FROM {schema}.{table}", conn)
                    return result

                # If the columns object is of type list...
                if isinstance(columns, list):

                    # Only one column is requested
                    if len(columns) == 1:
                        col_name = columns[0]
                        df = pd.read_sql(text(f"SELECT {col_name} FROM {schema}.{table}"), conn)
                        return df[col_name].dropna().unique().tolist()

                    # More columns requested
                    else:
                        # We need to build the query for SQLAlchemy
                        cols_str = ", ".join(columns)
                        return pd.read_sql(text(f"SELECT {cols_str} FROM {schema}.{table}"), conn)

                # If a string is requested
                elif isinstance(columns, str):
                    # Extracts that column
                    df = pd.read_sql(text(f"SELECT {columns} FROM {schema}.{table}"), conn)
                    return df[columns].dropna().unique().tolist()

                # If the object type is neither a string nor list returns None
                else:
                    print("Error: 'columns' must be a string or a list.")
                    return None

            # If anything happens (like, a table/column not found), returns None
            except Exception as e:
                print(f"Error with the database: {e}")
                return None
            
    def _build_join_graph(self, project = None, schema = None):
        """
        Build a graph of table relationships based on foreign keys.

        Input:
        - project: macroproject name. Optional.
        - schema: schema name. Optional.

        Output:
        - a dictionary where keys are table names and values are lists of tuples.
        """

        # Same logic as before, use the project name to extract the schema, or use the first one provided
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]

        # Inspector uses inspect to retrieve metadata from the database.
        inspector = inspect(self.engine)

        # Initialize empty graph
        graph = {}

        # For each table name obtained through the metadata...
        for table_name in inspector.get_table_names(schema):
            # ... add the table name to the graph dictionary and set an empty list as its value
            graph.setdefault(table_name, []) 

            # For each foreign key in that table...
            for fk in inspector.get_foreign_keys(table_name, schema):

                # Obtain referred tables, columns and constrained columns.
                # These are automatically extracted by inspector.get_foreign_keys().
                source_table = table_name
                target_table = fk['referred_table']
                source_columns = fk.get('constrained_columns', [])
                target_columns = fk.get('referred_columns', [])

                # If no connections between tables and columsn are detected, skip that foreign key
                if not source_columns or not target_columns:
                    continue

                # If instead the connections are found, we log them in the graph.
                graph.setdefault(target_table, [])

                graph[source_table].append((target_table, source_columns, target_columns))
                graph[target_table].append((source_table, target_columns, source_columns))

        return graph

    def _find_join_path(self, graph, start, target):
        """
        This function finds the shortest path between two tables in the join graph.
        
        Inputs:
        - graph: the connection between tables (following foreign keys and references).
        - start: the starting table.
        - target: the target table.

        Output:
        - path: a list composed by tuples (next table, left column for the join, right column for the join)
        """

        # CASE 1: If the start and target are the same, return an empty path
        if start == target:
            return []

        # This library helps to implement a queue for the breadth-first search (BFS) algorithm which is used to find the shortest paths in graphs
        queue = deque([(start,[])])
        visited = {start}

        # If a queue exists...
        while queue:
            # We remove the next item, which we call "current", in front of the queue
            # We obtain the current table (in which we virtually are) and then the rest of the path
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

    def _build_sample_details_query(self, project = None, schema = None):
        """
        This function builds the query needed to gather the short version of details of one specific individual (here called sample).
        
        Input:
        - project: macroproject name. Optional.
        - schema: schema name. Optional.
        
        Output:
        - a string with the final query to get all details for a specific individual.
        """
        # Same logic as before, use the project name to extract the schema, or use the first one provided
        # Starting to think I should make this into a function lol
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]

        # Here we need the mapped tables. Since I need information like Individual_ID, material ID..., I need to know
        # how the DB named the columns containing this information. This is the purpose of "mapping".

        # Let's extract the mapping for the project/schema we are working on.
        project_config = next(
            (p for p in self.config["database"]["projects"] if p["schema_name"] == schema),
            None
        )

        if project_config:
            mapping = project_config["mapping"]
        else:
            raise ValueError(f"No configuration found for schema: {schema}")


        # We use individual_id as the base column for the query (we use .get to avoid crashing)
        base_entry = mapping.get("individual_id", {})

        # The base table will be the one where to start the JOIN chain
        base_table = base_entry.get("base_table")
        base_key_col = base_entry.get("column_name")

        if not any([base_table, base_key_col]):
            raise ValueError(f"Mapping information for {base_entry} is required. Please check config.json.")

        # We build the graph of connections between tables.
        graph = self._build_join_graph(project=project, schema=schema)

        # Here we initialize the SELECT and JOIN parts of the SQL query
        select_parts = []
        join_parts = []

        # Here we create a set of JOINs to monitor because we don't want to duplicate them
        seen_joins = set()

        # The value 'base' here will be defined at the end of the query
        select_parts.append(f"base.{base_key_col} AS individual_id")

        # What fields we need to have an overview of a sample?
        requested_fields = project_config["summaries_fields"]["individual"]

        # For each concept/field in the mapping:
        for concept, info in mapping.items():
            # If its one of the required ones
            if concept in requested_fields:
                
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
                            f"LEFT JOIN {schema}.{next_table} AS {next_table} "
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
                FROM {schema}.{base_table} AS base
                {' '.join(join_parts)}
                WHERE base.{base_key_col} = :individual_id
            """

        return text(sql)

    def get_sample_details(self, individual_id, project=None, schema=None):
        """
        Obtain all the details that summarize an Individual/Sample current status.
        
        Input:
        - individual_id: the id of the Individual/Sample to analyze.
        - project: macroproject name. Optional.
        - schema: schema name. Optional.
        
        Output:
        - A pandas dataframe with the information requested.
        """
        # Build the query
        query = self._build_sample_details_query(project=project, schema=schema)

        # Send the query and retrieve result
        return pd.read_sql(query, self.engine, params={"individual_id": individual_id})

    def _build_long_sample_details_query(self, project = None, schema = None):
        """
        This function builds the query needed to gather the complete details of one specific individual (here called sample).
        
        Input:
        - project: macroproject name. Optional.
        - schema: schema name. Optional.
        
        Output:
        - a string with the final query.
        """
        # Same logic as before, use the project name to extract the schema, or use the first one provided
        # Starting to think I should make this into a function lol
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]

        project_config = next(
            (p for p in self.config["database"]["projects"] if p["schema_name"] == schema),
            None
        )

        if project_config:
            mapping = project_config["mapping"]
        else:
            raise ValueError(f"No configuration found for schema: {schema}")

        # We use individual_id as the base column for the query (we use .get to avoid crashing)
        base_entry = mapping.get("individual_id", {})

        # The base table will be the one where to start the JOIN chain
        base_table = base_entry.get("base_table")
        base_key_col = base_entry.get("column_name")

        if not any([base_table, base_key_col]):
            raise ValueError("mapping['individual_id'] information is required. Please check config.json.")

        graph = self._build_join_graph(project=project, schema=schema)

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
                        f"LEFT JOIN {schema}.{next_table} AS {next_table} "
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
            FROM {schema}.{base_table} AS base
            {' '.join(join_parts)}
            WHERE base.{base_key_col} = :individual_id
        """

        return text(sql)

    def get_long_sample_details(self, individual_id, project=None, schema=None):
        """
        Obtain all the details about an Individual/Sample current status.
        
        Input:
        - individual_id: the id of the Individual/Sample to analyze.
        - project: macroproject name. Optional.
        - schema: schema name. Optional.
        
        Output:
        - A pandas dataframe with the information requested.
        """
        query = self._build_long_sample_details_query(project=project, schema=schema)
        return pd.read_sql(query, self.engine, params={"individual_id": individual_id})
    
    def _build_project_details_query(self, project = None, schema = None):
        """
        This function builds the query needed to gather the complete details of one specific project.
        Here, by project, we don't mean the "macro-project" that cathegories (almost) everything a researcher is working on.
        We plan to distinguish the two categories better, but this will be changed later on.
        
        Input:
        - project: macroproject name. Optional.
        - schema: schema name. Optional.
        
        Output:
        - a string with the final query.
        """
        # Usual schema logic...
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]

        # We get everything associated with the macroproject we are working on.
        project_config = next(
            (p for p in self.config["database"]["projects"] if p["schema_name"] == schema),
            None
        )

        # Now we need the mapping information.
        if project_config:
            mapping = project_config["mapping"]
        else:
            raise ValueError(f"No configuration found for schema: {schema}")

        base_entry = mapping.get("individual_id", {})
        base_table = base_entry.get("base_table")
        base_key_col = base_entry.get("column_name")

        # Now our filter is the (micro)project id
        project_col = mapping.get("project_id", {}).get("column_name", "project_id")

        if not any([base_table, base_key_col]):
            raise ValueError(f"Mapping information is required. Please check config.json.")
        
        graph = self._build_join_graph(project=project, schema=schema)

        # Differently from the sample summary, the (micro)project summary requires extra step:
        # - Counting all samples associated with a specific (micro)project;
        # - Counting the total number of dna extractions;
        # - Counting the total number of libraries prepared;
        # - The average andogenous DNA obtained.
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

        # Here we apply the same logic as before...
        for concept, info in mapping.items():
            if concept in requested_fields.keys():
                target_table = info.get("base_table")
                target_column = info.get("column_name")

                if not target_table or not target_column:
                    continue

                # With the expection of slightly changing the query if we are interested in counting or averaging.
                if target_table == base_table:
                    if "DISTINCT" in requested_fields[concept][1]:
                        select_parts.append(f"COUNT(DISTINCT base.{target_column}) AS {requested_fields[concept][0]}")
                        continue
                    elif "AVG" in requested_fields[concept][1]:
                        select_parts.append(f"AVG(base.{target_column}) AS {requested_fields[concept][0]}")
                        continue

                # We find the connection between tables...
                path = self._find_join_path(graph, base_table, target_table)

                if path is None:
                    raise ValueError(f"No join path found between {base_table} and {target_table}")

                current_alias = "base"
                current_table = base_table

                for next_table, left_cols, right_cols in path:
                    if not left_cols or not right_cols:
                        continue

                    # And we build the JOIN query exactly as before.
                    join_key = (current_table, next_table)
                    if join_key not in seen_joins:
                        join_conditions = []
                        for left_col, right_col in zip(left_cols, right_cols):
                            join_conditions.append(
                                f"{current_alias}.{left_col} = {next_table}.{right_col}"
                            )

                        join_parts.append(
                            f"LEFT JOIN {schema}.{next_table} AS {next_table} "
                            f"ON {' AND '.join(join_conditions)}"  
                        )

                        seen_joins.add(join_key)

                    current_alias = next_table
                    current_table = next_table

                if "DISTINCT" in requested_fields[concept][1]:
                    select_parts.append(f"COUNT(DISTINCT {target_table}.{target_column}) AS {requested_fields[concept][0]}")
                elif "AVG" in requested_fields[concept][1]:
                    select_parts.append(f"AVG({target_table}.{target_column}) AS {requested_fields[concept][0]}")

        # And here we have the query
        sql = f"""
            SELECT
                {', '.join(select_parts)}
            FROM {schema}.{base_table} AS base
            {' '.join(join_parts)}
            WHERE base.{project_col} = :project_id
        """
        return text(sql)

    def get_project_details(self, project_id, project=None, schema=None):
        """
        Obtain all the details about a (micro)project current status.
        
        Input:
        - project_id: the id of the (micro)project to analyze.
        - project: macroproject name. Optional.
        - schema: schema name. Optional.
        
        Output:
        - A pandas dataframe with the information requested.
        """
        query = self._build_project_details_query(project=project, schema=schema)
        return pd.read_sql(query, self.engine, params={"project_id": project_id})

    def get_primary_keys(self, table_name, schema=None, project=None):
        """
        Recover the primary keys of a table in the database. 
        This is possible with simply inspect() but I don't want to keepy building the inspector.

        Inputs:
        - table_name : the table we are interested in.
        - project: macroproject name. Optional.
        - schema: schema name. Optional.

        Outputs:
        - The column names containing primary keys of the target table.
        """
        # Usual schema logic...
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]

        # Build the inspector.
        inspector = inspect(self.engine)

        # Obtain primary keys.
        pk_columns = inspector.get_pk_constraint(table_name, schema)
        return pk_columns.get('constrained_columns', [])

    def check_parent_from_child(self, parent_name, child_dataframe, conn, schema=None, project=None):
        """
        This function checks for parent table information when uploading child table information.
        It checks for the primary keys connection. 
        To avoid throwing errors, if a child has new values for the primary keys of the parent,
        a new row is also added to the parent and committed to the server.

        Input:
        - parent_name: name of the parent table;
        - child_datframe: a pandas DataFrame object with child table information;
        - conn: an established connection with the database of interest (sqlalchemy create_engine());
        - schema: name of the schema that contains the tables.

        Output:
        - Pass
        """
        # Usual schema logic...
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]
        
        # Recover the columns names of the parent's Primary Keys
        pk_columns = self.get_primary_keys(parent_name, schema, project)

        if not pk_columns:
            return print(f"Error: No primary key found for: {parent_name}")

        # Remove duplicates and NA from child info
        child_entries = child_dataframe[pk_columns].drop_duplicates().dropna()

        # Get information from parent, but only about the primary keys columns.
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

        # Final commit if there is any change in the dataset
        if new_rows_added:
            conn.commit()
            print(f"Updated the database on table '{parent_name}'. Please remember to check later the newly added information.")
        else:
            print(f"No new row for table '{parent_name}'.")
        
    def safe_update_table(self, table_name, edited_df, schema=None, project=None):
        """
        Updates table taking into consideration the data types, primary keys of the table and parent-child references. 
        If a row with the same primary key exists, it will be updated; otherwise, it will be inserted.

        Inputs:
        - table_name: target table to update.
        - edited_df: the new information to append or edit.
        - project: macroproject name. Optional.
        - schema: schema name. Optional.

        Output:
        - TRUE (Boolean) if the table has been safely updated.
        """
        # Usual schema logic...
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]

        # If there are no edits, return True
        if edited_df.empty:
            return True

        # First lets get constraint.
        pk_cols = self.get_primary_keys(table_name, schema=schema, project=project)

        # If we cannot access the primary keys, checking for references is impossible.
        if not pk_cols:
            print(f"Error: No primary key found for table {table_name}. Cannot perform UPSERT.")
            return False

        # Let's connect to the database
        try:
            with self.engine.begin() as conn:
                # Temporary staging table name
                staging_name = f"temp_staging_{table_name}"
                edited_df.to_sql(staging_name, conn, schema=schema, 
                                if_exists='replace', index = False)
                
                columns_to_update = [col for col in edited_df.columns if col not in pk_cols]
                
                col_names = ", ".join(edited_df.columns)
                pk_constraint = ", ".join(pk_cols)

                # We use inspector to obtain metadata of the columns (name and type)
                inspector = inspect(self.engine)
                database_cols = inspector.get_columns(table_name, schema=schema)
                
                select_parts = []

                # This might be a little bit hard coded in a way, but it is the only way I thought to update
                # columns using the same data type.
                for col in edited_df.columns:
                    col_info = next((database_col for database_col in database_cols if database_col['name'].lower() == col.lower()), None)

                    # The column type is contained in the metadata obtained by the inspector
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

                # If there are no columns to update, but only data to add, the new data is simply appended
                if not columns_to_update:
                    upsert_query = f"""
                        INSERT INTO {schema}.{table_name} ({col_names})
                        SELECT {select_clause} FROM {schema}.{staging_name}
                        ON CONFLICT ({pk_constraint}) DO NOTHING;
                    """
                else:
                    # We need to manage the data to edit
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
                    
                    
                    set_clause_sql = ", ".join(set_parts)
                    
                    # Here we update the rows
                    upsert_query = f"""
                        INSERT INTO {schema}.{table_name} ({col_names})
                        SELECT {select_clause} FROM {schema}.{staging_name}
                        ON CONFLICT ({pk_constraint}) 
                        DO UPDATE SET {set_clause_sql};
                    """
                
                conn.execute(text(upsert_query))

                conn.execute(text(f"DROP TABLE {schema}.{staging_name}"))

            # If everything went smoothly, we return True.
            return True
        
        except Exception as e:
            print(f"Database Error: {e}")
            return False

    def _get_parent_for_sheet(self, sheet_name):
        """
        Return the parent table for a sheet if a hierarchy entry exists in the config.json file.
        
        Inputs:
        - sheet_name: the target sheet/table.
        
        Output: 
        - the name of the parent table.
        """
        table_hierarchies = self.config.get("database", {}).get("table_hierarchies", {})
        sheet_config = table_hierarchies.get(sheet_name, {})
        return sheet_config.get("parent")

    def generate_excel_template(self, schema = None, project = None):
        """
        Generates the Excel upload template dinamically.
        
        Inputs:
        - project: macroproject name. Optional.
        - schema: schema name. Optional.

        Outputs:

        """
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]

        inspector = inspect(self.engine)
        tables = inspector.get_table_names(schema=schema)

        output_path = Path(__file__).resolve().parent.parent / "templates" / f"{schema}_excel_upload.xlsx"

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            for table in tables:
                columns = [col['name'] for col in inspector.get_columns(table, schema=schema)]
                
                empty_df = pd.DataFrame(columns=columns)
                empty_df.to_excel(writer, sheet_name=table, index=False)

    def upload_from_excel(self, xlsx_path, schema=None, project=None):
        """
        This function uploads on the database the information provided through an Excel File.

        Input:
        - xlsx_path: Excel file or path to it.
        - project: macroproject name. Optional.
        - schema: schema name. Optional.

        Ouput:
        - Pass
        """
        # Usual schema logic...
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]
            
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
                                self.check_parent_from_child(parent_name=parent_name, child_dataframe=data, conn=conn, schema=schema, project=project)

                            print(f"Attempting to insert {len(data)} rows into {sheet}...")

                            for col, val in default_values.items():
                                if col in data.columns:
                                    data[col] = data[col].fillna(val)
                            
                            success = self.safe_update_table(sheet, data, schema=schema, project=project)

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
  
    def _rotate_backups(self, extension, schema=None, project=None, max_backups = 5):
        '''
        This function deletes the oldest backup file if the number of backup files exceedes a certain amount.

        Input:
        - extension: the file extension (example, but not limited to: .xlsx, .tsv, .csv...)
        - max_backups: maximum number of backups allowed, after which the oldest file is deleted. DEFAULT = 5
        - project: macroproject name. Optional.
        - schema: schema name. Optional.

        Output:
        - Pass
        '''
        # Usual schema logic...
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]

        project_config = next(
            (p for p in self.config["database"]["projects"] if p["schema_name"] == schema),
            None
        )

        # Define the internal backup path
        internal_backups_path = Path(__file__).resolve().parent.parent / "backups"

        # If the user provides a different backup path, use that one
        configured_backups_path = (
            project_config.get("backups_path") if project_config else None
        )
        
        if configured_backups_path and str(configured_backups_path).strip():
            backup_root = Path(str(configured_backups_path).strip()).expanduser()
            if not backup_root.is_absolute():
                backup_root = Path(__file__).resolve().parent.parent / backup_root
            backups_dir = backup_root / "daily" / f"{schema}"
        else:
            backups_dir = internal_backups_path / "daily" / f"{schema}"

        # Make a "daily" folder if not already existent. It is always present when using the internal backup path.
        backups_dir.mkdir(parents=True, exist_ok=True)

        # Sorts backup files by date of creation
        files = sorted(
            backups_dir.glob(f"*{extension}"),
            key=lambda path: path.stat().st_mtime,
        )

        # If there are too many files, it deletes the oldest.
        while len(files) > max_backups:
            old_file = files.pop(0)
            try:
                os.remove(old_file)
                print(f"Old backup removed: {old_file}")
            except Exception as e:
                print(f"Error while removing old backup {old_file}: {e}")

        pass

    def get_tables_names(self, schema = None, project = None):
        """
        Obtain all tables names from the database.
        (Comment: I think I built this function out of frustration and I can update some older functions
        to use this function instead of blocks of code)

        Input: 
        - project: macroproject name. Optional.
        - schema: schema name. Optional.

        Output:
        - a list of tables names.
        """
        # Same ol' logic
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]

        inspector = inspect(self.engine)
        tables = [x for x in inspector.get_table_names(schema = schema)]
        
        return tables

    def save_backup(self, target, writer, keep_existing=False):
        """ 
        Internal function to save backups.
        
        Inputs:
        - target: backup to save.
        - writer
        - keep_existing (flag): this flag is set to True only in the case of backups that are never deleted (monthly ones)
        
        Output:
        - a message notifying the created backup.
        """
        # Monthly snapshots are created once and never replaced.
        if keep_existing and target.exists():
            print(f"Monthly backup already exists; keeping it: {target}")
            return
        # Set a temporary name for the backup
        temporary = target.with_name(f"{target.stem}.tmp{target.suffix}")
        # Try to write the temporary backup
        try:
            writer(temporary)
            os.replace(temporary, target)
            print(f"Created backup: {target}")
            return True
        except Exception as e:
            print(f"Backup failed for {target.name}: {e}")
            return False
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except Exception:
                    pass

    def write_postgresql_dump(self, path, schema = None, project = None):
        """
        Special function specifically for postgreSQL backups.
        
        Input: 
        - path: where to save the backup file.
        
        Return: 
        - a subprocess sent to the command line.
        """
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]
        
        # We first need the url of the database.
        url = self.engine.url

        # Here we write the command. pg_dump is the command used to create an sql backup.
        command = [
            "pg_dump",
            "--format=custom",
            "--file", str(path),
            "--host", str(url.host or self.host),
            "--port", str(url.port or self.port),
            "--dbname", self.db_name,
            "--schema", schema,
        ]
        if url.username:
            command.extend(["--username", url.username])

        # pg_dump must be installed and available on PATH.
        # It reads the password from PostgreSQL's password file, not this command.
        subprocess.run(command, check=True)

    def write_sqlite_export(self, path, schema = None, project = None):
        """
        Function to write the sqlite backup.
        
        Input: 
        - path: where to write the backup.
        
        Output:
        - command for the command line.
        """
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]
    
        # Connect and set an execution option.
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as source_connection:
            with source_connection.begin():
                with closing(sqlite3.connect(path)) as sqlite_connection:
                    with sqlite_connection:
                        tables = self.get_tables_names(schema=schema, project=project)
                        for table_name in tables:
                            dataframe = pd.read_sql_table(
                                table_name,
                                source_connection,
                                schema=schema,
                            )
                            dataframe.to_sql(
                                table_name,
                                sqlite_connection,
                                if_exists="replace",
                                index=False,
                            )

    def write_excel_export(self, path, project = None, schema = None):
        """
        Function to write the excel backup.
        
        Input: 
        - path: where to write the backup.
        
        Output:
        - command for the command line.
        """
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]
        
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as source_connection:
            with source_connection.begin():
                with pd.ExcelWriter(path, engine="openpyxl") as writer:
                    tables = self.get_tables_names(schema=schema, project=project)               
                    for table_name in tables:
                        dataframe = pd.read_sql_table(
                            table_name,
                            source_connection,
                            schema=schema,
                        )
                        dataframe.to_excel(
                            writer,
                            sheet_name=table_name,
                            index=False,
                        )

    def run_backup(self, schema = None, project = None):
        """Save daily and monthly PostgreSQL, SQLite, and Excel backups.
        Deletes the oldest daily backup according to _rotate_backups().
        
        Input:
        - project: macroproject name. Optional.
        - schema: schema name. Optional.
        
        Ouput:
        - Pass
        """
        if schema is None:
            if project is not None:
                schema = next((p["schema_name"] for p in self.config["database"]["projects"] if p["name"] == project), None)
            else:
                schema = self.schemas[0]

        project_config = next(
            (p for p in self.config["database"]["projects"] if p["schema_name"] == schema),
            None
        )

        if project_config is None:
            raise ValueError(f"No configured project found for schema: {schema}")

        # The backup path is resolved relative to the directory containing config.json.
        config_dir = Path(__file__).resolve().parent.parent
        configured_path = project_config.get("backups_path")

        # If the user provides a custom backup path...
        if configured_path and str(configured_path).strip():
            backup_root = Path(str(configured_path).strip()).expanduser()
            if not backup_root.is_absolute():
                backup_root = config_dir / backup_root
        
        # If not, use the "internal" backup path
        else:
            backup_root = config_dir / "backups"

        # Daily backups directory
        daily_dir = backup_root / "daily" / f"{schema}"
        # Monthly backups directory
        monthly_dir = backup_root / "monthly" / f"{schema}"
        # Make these directories if they do not exist
        daily_dir.mkdir(parents=True, exist_ok=True)
        monthly_dir.mkdir(parents=True, exist_ok=True)

        # Obtain the current date and time
        now = datetime.now()
        backup_periods = [
            (daily_dir, now.strftime("%Y%m%d"), False),
            (monthly_dir, now.strftime("%Y%m"), True),
        ]

        warnings = []

        for directory, period, keep_existing in backup_periods:
            
            success_pg = self.save_backup(
                directory / f"{period}.dump",
                lambda path: self.write_postgresql_dump(path, schema=schema, project=project),
                keep_existing=keep_existing,
            )
            if not success_pg:
                warnings.append(f"PostgreSQL dump failed for {period} (is pg_dump installed?)")
            
            success_sq = self.save_backup(
                directory / f"{period}.sqlite3",
                lambda path: self.write_sqlite_export(path, schema=schema, project=project),
                keep_existing=keep_existing,
            )
            if not success_sq:
                warnings.append(f"SQLite export failed for {period}")
            
            success_ex = self.save_backup(
                directory / f"{period}.xlsx",
                lambda path: self.write_excel_export(path, schema=schema, project=project),
                keep_existing=keep_existing,
            )
            if not success_ex:
                warnings.append(f"Excel export failed for {period}")

        for extension in (".dump", ".sqlite3", ".xlsx"):
            self._rotate_backups(
                extension,
                schema=schema,
                project=project,
                max_backups=5,
            )
        
        return warnings

if __name__ == "__main__":
    try:
        user = input("User: ")
        password = input("Password: ")
        db = LabDatabase(user=user, password=password)
        print(f"Connection to the {db.host} for user {db.user} created successfully.")
    except Exception as ex:
        print(f"Connection could not be created due to the following error:\n", ex)
