import pandas as pd
import re
from typing import Dict, Any

def build_sql_mapping(mapping_path) -> Dict[str, Any]:
    """
    Build SQL mapping from Excel file.
    Extracts source tables, joins, filters, and target column mappings.
    """
    print("Building SQL mapping from Excel...")
    print(f"Reading: {mapping_path}")

    # Read Excel file
    df = pd.read_excel(mapping_path)
    df = df.fillna("")

    print(f"Loaded {len(df)} rows")
    print(f"Columns: {list(df.columns)}")
    print(f"\nFirst few rows:\n{df.head()}\n")

    # Initialize collections
    source_tables = set()
    joins = []
    filters = []
    target_columns = {}

    # Track current state
    current_section = None
    in_target_section = False

    # -----------------------------------
    # Regex patterns
    # -----------------------------------
    # Pattern to extract table names from FROM/JOIN clauses
    from_join_pattern = re.compile(
        r"(?:FROM|JOIN)\s+([A-Z_][A-Z0-9_]*)",
        re.IGNORECASE
    )

    # Pattern to find driving table (first table with alias)
    driving_table_pattern = re.compile(
        r"^\s*([A-Z_][A-Z0-9_]*)\s+[A-Z]\b",
        re.IGNORECASE
    )

    # Pattern to extract JOIN keys
    join_key_pattern = re.compile(
        r"([A-Z_][A-Z0-9_]*)\.([A-Z_][A-Z0-9_]*)\s*=\s*([A-Z_][A-Z0-9_]*)\.([A-Z_][A-Z0-9_]*)",
        re.IGNORECASE
    )

    # -----------------------------------
    # Process each row
    # -----------------------------------
    for idx, row in df.iterrows():
        # Get section and logic (handle different possible column names)
        section = str(row.get("Section", row.get("section", ""))).strip()
        logic = str(row.get("Logic / Description",
                           row.get("Logic",
                           row.get("Description",
                           row.get("logic", ""))))).strip()

        # Skip empty rows
        if not section and not logic:
            continue

        # -----------------------------
        # Detect section changes
        # -----------------------------
        if section and section not in ["", "nan"]:
            current_section = section.upper()
            print(f"  Section: {current_section}")

            # Check if we're entering the target column section
            if "TARGET" in current_section and "COLUMN" in current_section:
                in_target_section = True
                print("  Entering TARGET COLUMN section")
                continue

        # -----------------------------
        # Process SQL/LOGIC sections
        # -----------------------------
        if not in_target_section and logic and logic != "":
            logic_upper = logic.upper()

            # Extract source tables from FROM/JOIN
            if "FROM" in logic_upper or "JOIN" in logic_upper:
                # Find driving table
                if "JOIN" in logic_upper and "FROM" not in logic_upper:
                    m = driving_table_pattern.search(logic)
                    if m:
                        table_name = m.group(1).upper()
                        source_tables.add(table_name)
                        print(f"    Found driving table: {table_name}")

                # Extract all tables from FROM/JOIN
                matches = from_join_pattern.findall(logic)
                for tbl in matches:
                    table_name = tbl.upper()
                    source_tables.add(table_name)
                    print(f"    Found table: {table_name}")

            # -----------------------------
            # Process JOIN clauses
            # -----------------------------
            if current_section and "JOIN" in current_section:
                # Determine join type
                join_type = "INNER"
                if "LEFT" in current_section:
                    join_type = "LEFT"
                elif "RIGHT" in current_section:
                    join_type = "RIGHT"
                elif "OUTER" in current_section or "FULL" in current_section:
                    join_type = "OUTER"

                # Extract join keys
                keys = []
                for m in join_key_pattern.findall(logic):
                    key_info = {
                        "left_table": m[0].upper(),
                        "left_column": m[1].upper(),
                        "right_table": m[2].upper(),
                        "right_column": m[3].upper(),
                    }
                    keys.append(key_info)
                    print(f"    Join key: {key_info['left_table']}.{key_info['left_column']} = {key_info['right_table']}.{key_info['right_column']}")

                joins.append({
                    "type": join_type,
                    "sql": logic,
                    "keys": keys
                })
                print(f"    Added {join_type} JOIN")

            # -----------------------------
            # Process FILTER / CONDITION clauses
            # Captures: FILTER CONDITIONS, WHERE clauses,
            #           ADDITIONAL CONDITIONS, any CONDITION section
            # -----------------------------
            elif current_section and any(
                kw in current_section
                for kw in ("FILTER", "WHERE", "CONDITION", "ADDITIONAL")
            ):
                filters.append(logic)
                print(f"    Added filter: {logic[:80]}...")

        # -----------------------------
        # Process TARGET COLUMN section
        # -----------------------------
        elif in_target_section:
            # Row layout (from Excel):
            #   col 0  "Section"               → Target Column Name
            #   col 1  "Logic / Description"   → Source Table
            #   col 2  "Unnamed: 2"            → Source Column Name(s)
            #   col 3  "Unnamed: 3"            → Transformation / Business Rule  ← we want this
            #   col 4  "Unnamed: 4"            → Reference / Rule Description
            target_col = section

            # col 1 = Source Table  (used for table extraction only)
            source_table_val = logic

            # col 2 = Source Column Name / Expression  (e.g. LINE_AMOUNT > 10000)
            source_col_expr = str(
                row.get("Unnamed: 2",
                row.get("Source Column Name(s)",
                row.get("source_column", "")))
            ).strip()

            # col 3 = Transformation / Business Rule
            transformation_rule = str(
                row.get("Unnamed: 3",
                row.get("Transformation / Business Rule",
                row.get("transformation", "")))
            ).strip()

            # Build composite rule: "source_expr | transformation_rule"
            # This catches changes to either the source expression OR the rule text
            parts = [p for p in (source_col_expr, transformation_rule) if p and p not in ("", "nan")]
            rule = " | ".join(parts) if parts else (logic if logic not in ("", "nan") else "")

            if target_col and target_col not in ["", "nan"] and rule and rule not in ["", "nan"]:
                target_columns[target_col] = rule
                print(f"    Target column: {target_col} = {rule[:80]}...")

                # Extract table names from source table field and rule
                for text in (source_table_val, rule):
                    tables_in_text = re.findall(r"\b([A-Z_][A-Z0-9_]*)\.", text)
                    for t in tables_in_text:
                        if t not in {"SYSTEM", "CASE", "WHEN", "THEN", "ELSE", "END",
                                     "SELECT", "FROM", "WHERE", "AND", "OR", "NOT"}:
                            source_tables.add(t.upper())
                # Also treat a bare source-table name (no dot) in source_table_val
                bare = source_table_val.strip().upper()
                if bare and re.match(r'^[A-Z_][A-Z0-9_]*$', bare) and bare != "SYSTEM":
                    source_tables.add(bare)

    # -----------------------------
    # Clean up source tables
    # -----------------------------
    # Remove column-like patterns (things ending with _ID, _CD, etc.)
    cleaned_tables = {
        t for t in source_tables
        if not re.search(r"_ID$|_CD$|_DT$|_DATE$|_STATUS$|_AMOUNT$|_TYPE$|_FLAG$", t)
    }

    # Print summary
    print(f"\n{'='*60}")
    print(f"MAPPING SUMMARY")
    print(f"{'='*60}")
    print(f"Source Tables ({len(cleaned_tables)}): {sorted(cleaned_tables)}")
    print(f"Joins ({len(joins)})")
    for j in joins:
        print(f"   - {j['type']}: {len(j['keys'])} keys")
    print(f"Filters ({len(filters)})")
    print(f"Target Columns ({len(target_columns)})")

    return {
        "source_tables": sorted(cleaned_tables),
        "joins": joins,
        "filters": filters,
        "target_columns": target_columns
    }