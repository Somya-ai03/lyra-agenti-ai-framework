# core/scenarios/target_scenarios_builder.py
import numpy as np
import uuid
import re
import pandas as pd
from pathlib import Path
from collections import Counter
from typing import Dict, Any
from difflib import get_close_matches
import os
import json
from datetime import datetime, timedelta
import random

from core.scenarios.sql_mapping_builder import build_sql_mapping



def normalize_logic(logic: str) -> str:
    import re

    if not logic:
        return logic

    logic = logic.strip()

    # Convert IF → CASE WHEN
    logic = re.sub(r"\bif\b", "CASE WHEN", logic, flags=re.IGNORECASE)
    logic = re.sub(r"\bthen\b", "THEN", logic, flags=re.IGNORECASE)
    logic = re.sub(r"\belse\b", "ELSE", logic, flags=re.IGNORECASE)

    # Add END if missing
    if "CASE WHEN" in logic.upper() and "END" not in logic.upper():
        logic += " END"

    return logic

# Common abbreviation mappings
def _is_internal_column(col: str) -> bool:
    """
    Return True for columns that are internal join artifacts, not real target columns.
    """
    upper = col.upper()
    if "_SRC_" in upper:
        return True
    if upper == "VARIANCE" or (
        upper.startswith("VARIANCE_") and
        any(x in upper for x in ("_SRC_", "_TYPE", "_VALUE"))
    ):
        return True
    if upper in ("RECORD_ID", "RECORDID"):
        return True
    return False


COMMON_ABBREVIATIONS = {
    'cpty': 'counterparty',
    'cust': 'customer',
    'acct': 'account',
    'addr': 'address',
    'qty': 'quantity',
    'amt': 'amount',
    'curr': 'currency',
    'instr': 'instrument',
    'pos': 'position',
    'ref': 'reference',
    'desc': 'description',
    'cd': 'code',
    'dt': 'date',
    'tm': 'time',
    'num': 'number',
    'nbr': 'number',
    'pct': 'percent',
}


# Get the directory where the current script is located
# core/scenarios/ -> core/ -> project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

PROFILER_DIR = os.path.join(DATA_DIR, "profiled")
REFERENCE_DIR = os.path.join(DATA_DIR, "raw", "reference_tables")
SAMPLE_DIR = os.path.join(DATA_DIR, "sample")
MAPPING_DIR = os.path.join(DATA_DIR, "mapping_document")
SCENARIOS_DIR = os.path.join(DATA_DIR, "scenarios")

#-------------------------------------------------
# Main function to build target scenarios
#-------------------------------------------------


def find_driving_table(join_pairs):
    """
    Find the driving table based on frequency of appearance in join pairs.
    """
    table_counts = Counter()

    for left_table, _, right_table, _ in join_pairs:
        table_counts[left_table] += 1
        table_counts[right_table] += 1

    driving_table = table_counts.most_common(1)[0][0]

    print("Table frequency:")
    for table, count in table_counts.most_common():
        marker = ">>>" if table == driving_table else "  "
        print(f"{marker} {table}: {count} occurrences")

    return driving_table



def expand_abbreviations(col_name):
    """Expand common abbreviations in column names."""
    col_lower = col_name.lower()

    parts = col_lower.split('_')
    expanded_parts = []

    for part in parts:
        if part in COMMON_ABBREVIATIONS:
            expanded_parts.append(COMMON_ABBREVIATIONS[part])
        else:
            expanded_parts.append(part)

    return '_'.join(expanded_parts)

def normalize_column_name(col_name):
    """Normalize column name by removing underscores and converting to lowercase."""
    return col_name.replace('_', '').replace('-', '').lower()

def find_matching_column(target_col, df_columns, table_name):
    """
    Find the actual column name in the dataframe that matches the target column.
    Handles abbreviations and various naming conventions.
    """
    # 1. Exact match (case-insensitive)
    for col in df_columns:
        if col.lower() == target_col.lower():
            return col

    # 2. Normalize and match (ignoring underscores, hyphens, case)
    normalized_target = normalize_column_name(target_col)

    for col in df_columns:
        if normalize_column_name(col) == normalized_target:
            print(f"  Matched '{target_col}' -> '{col}' in {table_name}")
            return col

    # 3. Expand abbreviations and try matching
    expanded_target = expand_abbreviations(target_col)
    normalized_expanded = normalize_column_name(expanded_target)

    for col in df_columns:
        if normalize_column_name(col) == normalized_expanded:
            print(f"  Matched '{target_col}' (expanded to '{expanded_target}') -> '{col}' in {table_name}")
            return col

    # 4. Try partial matching
    for col in df_columns:
        col_normalized = normalize_column_name(col)
        if normalized_expanded in col_normalized or col_normalized in normalized_expanded:
            if len(normalized_expanded) >= 4:
                print(f"  Partial match '{target_col}' (expanded to '{expanded_target}') -> '{col}' in {table_name}")
                return col

    # 5. Fuzzy match as last resort
    df_cols_lower = [c.lower() for c in df_columns]

    close_matches = get_close_matches(target_col.lower(), df_cols_lower, n=1, cutoff=0.7)

    if not close_matches:
        close_matches = get_close_matches(expanded_target.lower(), df_cols_lower, n=1, cutoff=0.7)

    if close_matches:
        for col in df_columns:
            if col.lower() == close_matches[0]:
                print(f"  Fuzzy matched '{target_col}' -> '{col}' in {table_name}")
                return col

    print(f"  Could not find match for '{target_col}' in {table_name}")
    print(f"     Expanded to: '{expanded_target}'")
    print(f"     Available columns: {', '.join(df_columns)}")
    return None


def parse_filter_condition(condition_str, dfs, alias_map=None):
    """
    Parse SQL-style filter conditions and apply them to the dataframe.
    """
    if alias_map is None:
        alias_map = {}  # Will be resolved dynamically from join SQL

    filters = []

    conditions = re.split(r'\s+AND\s+', condition_str, flags=re.IGNORECASE)

    for cond in conditions:
        cond = cond.strip()

        pattern = r"([A-Z]+)\.(\w+)\s*(=|<>|!=|>=|<=|>|<|LIKE|IN)\s*(.+)"
        match = re.match(pattern, cond, re.IGNORECASE)

        if match:
            alias = match.group(1)
            column = match.group(2)
            operator = match.group(3).upper()
            value = match.group(4).strip()

            value = value.strip("'\"")

            table_name = alias_map.get(alias, alias)

            filters.append({
                'alias': alias,
                'table': table_name,
                'column': column,
                'operator': operator,
                'value': value,
                'original': cond
            })

            print(f"  Parsed: {alias}.{column} {operator} '{value}'")
        else:
            print(f"  Could not parse condition: {cond}")

    return filters

def apply_filters(df, filters, dfs):
    """
    Apply parsed filter conditions to the dataframe.
    """
    result = df.copy()

    print(f"\nApplying filters...")
    print(f"Starting rows: {len(result)}\n")

    for filter_dict in filters:
        column = filter_dict['column']
        operator = filter_dict['operator']
        value = filter_dict['value']
        table = filter_dict['table']

        actual_column = find_matching_column(column, result.columns.tolist(), 'result')

        if not actual_column:
            print(f"  Skipping filter: Column '{column}' not found in result")
            continue

        before = len(result)

        try:
            if operator == '=':
                if value.replace('-', '').replace('.', '').isdigit():
                    if '.' in value:
                        value = float(value)
                    else:
                        value = int(value)
                result = result[result[actual_column] == value]

            elif operator in ['<>', '!=']:
                if value.replace('-', '').replace('.', '').isdigit():
                    if '.' in value:
                        value = float(value)
                    else:
                        value = int(value)
                result = result[result[actual_column] != value]

            elif operator == '>':
                if '-' in value and len(value) == 10:
                    result = result[pd.to_datetime(result[actual_column]) > pd.to_datetime(value)]
                else:
                    value = float(value) if '.' in value else int(value)
                    result = result[result[actual_column] > value]

            elif operator == '<':
                if '-' in value and len(value) == 10:
                    result = result[pd.to_datetime(result[actual_column]) < pd.to_datetime(value)]
                else:
                    value = float(value) if '.' in value else int(value)
                    result = result[result[actual_column] < value]

            elif operator == '>=':
                if '-' in value and len(value) == 10:
                    result = result[pd.to_datetime(result[actual_column]) >= pd.to_datetime(value)]
                else:
                    value = float(value) if '.' in value else int(value)
                    result = result[result[actual_column] >= value]

            elif operator == '<=':
                if '-' in value and len(value) == 10:
                    result = result[pd.to_datetime(result[actual_column]) <= pd.to_datetime(value)]
                else:
                    value = float(value) if '.' in value else int(value)
                    result = result[result[actual_column] <= value]

            elif operator == 'LIKE':
                pattern = value.replace('%', '.*').replace('_', '.')
                result = result[result[actual_column].astype(str).str.match(pattern, case=False)]

            elif operator == 'IN':
                in_values = re.findall(r"'([^']*)'", value)
                result = result[result[actual_column].isin(in_values)]

            after = len(result)
            print(f"  {filter_dict['original']}")
            print(f"     Rows: {before} -> {after} (removed {before - after})")

        except Exception as e:
            print(f"  Error applying filter '{filter_dict['original']}': {str(e)}")
            result = df.copy()
            break

    print(f"\nFinal rows after filters: {len(result)}")
    return result

def resolve_join_pairs(join_pairs, dfs):
    """
    Resolve join pairs with actual column names from dataframes.
    """
    resolved_pairs = []

    print("Resolving column names...\n")

    for left_table, left_key, right_table, right_key in join_pairs:
        print(f"Processing: {left_table}.{left_key} = {right_table}.{right_key}")

        actual_left_key = find_matching_column(left_key, dfs[left_table].columns.tolist(), left_table)
        actual_right_key = find_matching_column(right_key, dfs[right_table].columns.tolist(), right_table)

        if actual_left_key and actual_right_key:
            resolved_pairs.append((left_table, actual_left_key, right_table, actual_right_key))
            print(f"  Resolved: {left_table}.{actual_left_key} = {right_table}.{actual_right_key}\n")
        else:
            print(f"  Failed to resolve join pair\n")

    return resolved_pairs


def extract_alias_map(join_config):
    """
    Automatically extract table alias mappings from SQL join configuration.
    """
    alias_map = {}

    print("Extracting table aliases from SQL...\n")

    for config in join_config:
        sql = config['sql']

        main_pattern = r'^\s*(\w+)\s+([A-Z]+)\s+'
        main_match = re.match(main_pattern, sql)
        if main_match:
            table_name = main_match.group(1)
            alias = main_match.group(2)
            if table_name not in ['INNER', 'LEFT', 'RIGHT', 'OUTER', 'JOIN', 'ON', 'AND', 'OR']:
                alias_map[alias] = table_name
                print(f"  Found: {alias} -> {table_name}")

        join_pattern = r'JOIN\s+(\w+)\s+([A-Z]+)\s+'
        for match in re.finditer(join_pattern, sql, re.IGNORECASE):
            table_name = match.group(1)
            alias = match.group(2)
            if table_name not in ['INNER', 'LEFT', 'RIGHT', 'OUTER', 'ON', 'AND', 'OR']:
                alias_map[alias] = table_name
                print(f"  Found: {alias} -> {table_name}")

    print(f"\nExtracted {len(alias_map)} table aliases")
    return alias_map


def extract_alias_map_advanced(join_config):
    """
    Advanced version that handles more SQL patterns.
    """
    alias_map = {}

    print("Extracting table aliases from SQL...\n")

    for config in join_config:
        sql = config['sql']

        sql = ' '.join(sql.split())

        pattern = r'\b(\w+)\s+([A-Z]{1,3})\s+(?:INNER|LEFT|RIGHT|OUTER|JOIN|ON|,|\))'

        for match in re.finditer(pattern, sql, re.IGNORECASE):
            table_name = match.group(1)
            alias = match.group(2)

            sql_keywords = ['ON', 'AS', 'AND', 'OR', 'IN', 'IS', 'NOT', 'NULL', 'INNER', 'LEFT', 'RIGHT', 'OUTER', 'JOIN']

            if table_name.upper() not in sql_keywords and alias.upper() not in sql_keywords:
                alias_map[alias] = table_name
                print(f"  Found: {alias} -> {table_name}")

    first_table_pattern = r'^\s*(\w+)\s+([A-Z]{1,3})\s+'
    for config in join_config:
        sql = config['sql']
        match = re.match(first_table_pattern, sql)
        if match:
            table_name = match.group(1)
            alias = match.group(2)
            sql_keywords = ['SELECT', 'FROM', 'WHERE', 'INNER', 'LEFT', 'RIGHT', 'OUTER', 'JOIN']
            if table_name.upper() not in sql_keywords and alias.upper() not in sql_keywords:
                if alias not in alias_map:
                    alias_map[alias] = table_name
                    print(f"  Found: {alias} -> {table_name}")

    print(f"\nExtracted {len(alias_map)} table aliases")
    return alias_map

def join_dataframes_with_resolution(dfs, join_config, join_pairs, driving_table=None):
    """
    Join dataframes with automatic column name resolution.
    """
    from collections import Counter

    if driving_table is None:
        table_counts = Counter()
        for left_table, _, right_table, _ in join_pairs:
            table_counts[left_table] += 1
            table_counts[right_table] += 1
        driving_table = table_counts.most_common(1)[0][0]
        print(f"Auto-detected driving table: {driving_table}\n")

    resolved_join_pairs = resolve_join_pairs(join_pairs, dfs)

    if not resolved_join_pairs:
        print("No valid join pairs found after resolution!")
        return None

    result = dfs[driving_table].copy()
    print(f"\n{'='*60}")
    print(f"Starting with {driving_table}: {len(result)} rows")
    print(f"{'='*60}\n")

    joined_tables = {driving_table}

    for left_table, left_key, right_table, right_key in resolved_join_pairs:
        join_type = 'inner'

        for config in join_config:
            if config['type'] == 'LEFT' and right_table in config['sql']:
                join_type = 'left'
                break

        if left_table in joined_tables and right_table not in joined_tables:
            print(f"{join_type.upper()} joining {right_table}")
            print(f"  ON {left_table}.{left_key} = {right_table}.{right_key}")

            before_rows = len(result)

            result = result.merge(
                dfs[right_table],
                left_on=left_key,
                right_on=right_key,
                how=join_type,
                suffixes=('', f'_{right_table}')
            )

            joined_tables.add(right_table)
            after_rows = len(result)

            print(f"  Rows: {before_rows} -> {after_rows} ({after_rows - before_rows:+d})")
            print()

    return result


def join_and_filter_dataframes_auto(dfs, join_config, join_pairs, filter_conditions=None, driving_table=None):
    """
    Complete pipeline with automatic alias extraction.
    """

    alias_map = extract_alias_map_advanced(join_config)

    result = join_dataframes_with_resolution(dfs, join_config, join_pairs, driving_table)

    if result is None:
        return None

    if filter_conditions:
        print(f"\n{'='*60}")
        print(f"APPLYING FILTERS")
        print(f"{'='*60}")

        for condition in filter_conditions:
            print(f"\nFilter condition: {condition}")
            filters = parse_filter_condition(condition, dfs, alias_map)
            result = apply_filters(result, filters, dfs)

    return result


def extract_join_pairs_advanced(join_config):
    """
    Extract join pairs from SQL with proper alias resolution.
    Supports single-letter (O, C, P) and multi-letter aliases (OL, CUR, PAY).
    """
    join_pairs = []
    alias_map = {}

    for config in join_config:
        sql = config['sql']

        # Match: TABLE_NAME ALIAS  (alias = 1-10 letters/digits)
        # Exclude SQL keywords
        sql_keywords = {
            'INNER', 'JOIN', 'LEFT', 'RIGHT', 'OUTER', 'FULL', 'CROSS',
            'ON', 'AND', 'OR', 'WHERE', 'FROM', 'SELECT', 'AS', 'IN',
            'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'NOT', 'NULL', 'IS',
            'SET', 'INTO', 'VALUES', 'UPDATE', 'DELETE', 'INSERT', 'TABLE',
            'CREATE', 'DROP', 'ALTER', 'INDEX', 'VIEW', 'LIKE', 'BETWEEN',
        }
        table_alias_pattern = r'([A-Z_][A-Z0-9_]+)\s+([A-Z][A-Z0-9]{0,9})\b'

        for match in re.finditer(table_alias_pattern, sql, re.IGNORECASE):
            table_name = match.group(1).upper()
            alias = match.group(2).upper()
            if table_name not in sql_keywords and alias not in sql_keywords:
                alias_map[alias] = table_name

        # Match join conditions: ALIAS.COLUMN = ALIAS.COLUMN
        # Alias can be 1-10 letters/digits
        join_condition_pattern = r'([A-Z][A-Z0-9]{0,9})\.([A-Z_][A-Z0-9_]*)\s*=\s*([A-Z][A-Z0-9]{0,9})\.([A-Z_][A-Z0-9_]*)'

        for match in re.finditer(join_condition_pattern, sql, re.IGNORECASE):
            left_alias = match.group(1).upper()
            left_key = match.group(2).upper()
            right_alias = match.group(3).upper()
            right_key = match.group(4).upper()

            left_table = alias_map.get(left_alias, left_alias)
            right_table = alias_map.get(right_alias, right_alias)

            join_pairs.append((left_table, left_key, right_table, right_key))
            print(f"  {left_table}.{left_key} = {right_table}.{right_key}")

    return join_pairs

def force_join_compatibility(dfs, join_pairs, driving_table):
    """
    Override IDs in joined tables to ensure compatibility with driving table.
    """
    print(f"\n{'='*60}")
    print(f"FORCE JOIN COMPATIBILITY (Testing Mode)")
    print(f"{'='*60}\n")

    driver_df = dfs[driving_table]

    for left_table, left_key, right_table, right_key in join_pairs:
        if left_table == driving_table or left_table in [driving_table]:

            print(f"Checking: {left_table}.{left_key} -> {right_table}.{right_key}")

            left_df = dfs[left_table]
            right_df = dfs[right_table]

            left_col = find_matching_column(left_key, left_df.columns.tolist(), left_table)
            right_col = find_matching_column(right_key, right_df.columns.tolist(), right_table)

            if not left_col or not right_col:
                print(f"  Could not find columns, skipping...")
                continue

            left_values = set(left_df[left_col].dropna().unique())
            right_values = set(right_df[right_col].dropna().unique())

            matches = left_values & right_values
            match_rate = len(matches) / len(left_values) if len(left_values) > 0 else 0

            print(f"  Left table unique values: {len(left_values)}")
            print(f"  Right table unique values: {len(right_values)}")
            print(f"  Matching values: {len(matches)} ({match_rate:.1%})")

            if match_rate < 0.5:
                print(f"  Low match rate! Overriding {right_table}.{right_col}...")

                left_values_list = list(left_values)
                right_df_len = len(right_df)

                np.random.seed(42)
                new_values = np.random.choice(left_values_list, size=right_df_len, replace=True)

                dfs[right_table][right_col] = new_values

                print(f"  Overridden {right_df_len} rows in {right_table}.{right_col}")
                print(f"     New unique values: {len(dfs[right_table][right_col].unique())}")
            else:
                print(f"  Good match rate, no override needed")

            print()

    return dfs


def force_join_compatibility_sequential(dfs, join_pairs, driving_table):
    """
    Advanced version that handles sequential joins.
    """
    print(f"\n{'='*60}")
    print(f"FORCE JOIN COMPATIBILITY - SEQUENTIAL (Testing Mode)")
    print(f"{'='*60}\n")

    processed_tables = {driving_table}

    for left_table, left_key, right_table, right_key in join_pairs:
        if left_table in processed_tables and right_table not in processed_tables:

            print(f"Processing: {left_table}.{left_key} -> {right_table}.{right_key}")

            left_df = dfs[left_table]
            right_df = dfs[right_table]

            left_col = find_matching_column(left_key, left_df.columns.tolist(), left_table)
            right_col = find_matching_column(right_key, right_df.columns.tolist(), right_table)

            if not left_col or not right_col:
                print(f"  Could not find columns, skipping...")
                continue

            left_values = left_df[left_col].dropna().unique()
            right_values = right_df[right_col].dropna().unique()

            left_set = set(left_values)
            right_set = set(right_values)
            matches = left_set & right_set

            print(f"  Left ({left_table}): {len(left_values)} unique values")
            print(f"  Right ({right_table}): {len(right_values)} unique values")
            print(f"  Matches: {len(matches)}")

            if len(matches) == 0 or len(matches) / len(left_values) < 0.3:
                print(f"  Insufficient matches! Overriding {right_table}.{right_col}...")

                right_df_len = len(right_df)
                left_values_list = list(left_values)

                np.random.seed(42)

                if right_df_len <= len(left_values_list):
                    new_values = left_values_list[:right_df_len]
                else:
                    repeats = (right_df_len // len(left_values_list)) + 1
                    new_values = (left_values_list * repeats)[:right_df_len]
                    np.random.shuffle(new_values)

                dfs[right_table][right_col] = new_values

                print(f"  Updated {right_df_len} rows")
                print(f"     New unique values: {len(dfs[right_table][right_col].unique())}")
                print(f"     Sample values: {list(dfs[right_table][right_col].unique()[:5])}")
            else:
                print(f"  Sufficient matches ({len(matches)}), no override needed")

            processed_tables.add(right_table)
            print()

    return dfs


def join_and_filter_with_force_compatibility(dfs, join_config, join_pairs, filter_conditions=None,
                                             driving_table=None, force_compatibility=True):
    """
    Complete pipeline with optional forced join compatibility.
    """
    from collections import Counter

    if driving_table is None:
        table_counts = Counter()
        for left_table, _, right_table, _ in join_pairs:
            table_counts[left_table] += 1
            table_counts[right_table] += 1
        driving_table = table_counts.most_common(1)[0][0]
        print(f"Auto-detected driving table: {driving_table}")

    if force_compatibility:
        dfs = force_join_compatibility_sequential(dfs, join_pairs, driving_table)

    alias_map = extract_alias_map_advanced(join_config)

    result = join_dataframes_with_resolution(dfs, join_config, join_pairs, driving_table)

    if result is None:
        return None

    if filter_conditions:
        print(f"\n{'='*60}")
        print(f"APPLYING FILTERS")
        print(f"{'='*60}")

        for condition in filter_conditions:
            print(f"\nFilter condition: {condition}")
            filters = parse_filter_condition(condition, dfs, alias_map)
            result = apply_filters(result, filters, dfs)

    return result


def identify_primary_keys(df, table_name):
    """
    Identify likely primary key columns in the dataframe.
    Works with any mapping file — no hardcoded column names.
    """
    if df is None or df.empty or len(df.columns) == 0:
        print(f"  Warning: empty dataframe for {table_name}, no keys identified")
        return []

    pk_candidates = []

    # Strategy 1: Look for columns with 'id' in the name that are unique
    for col in df.columns:
        if 'id' in col.lower() and df[col].nunique() == len(df):
            pk_candidates.append(col)

    # Strategy 2: Look for columns with 'id' in the name (even if not fully unique)
    if not pk_candidates:
        for col in df.columns:
            if ('id' in col.lower() or 'key' in col.lower() or 'code' in col.lower()):
                pk_candidates.append(col)
                break  # Take the first one

    # Strategy 3: Look for any unique columns
    if not pk_candidates:
        for col in df.columns:
            if df[col].nunique() == len(df) and df[col].notna().all():
                pk_candidates.append(col)
                break  # Take the first one

    # Strategy 4: Use first column as last resort
    if not pk_candidates:
        pk_candidates = [df.columns[0]]

    print(f"  Identified primary keys for {table_name}: {pk_candidates}")
    return pk_candidates


def serialize_value(value):
    """Convert pandas/numpy types to JSON-serializable types."""
    if pd.isna(value):
        return None
    # numpy scalar aliases like np.int64/np.float32 are generic aliases and
    # may raise a "Generic type with type arguments" error in isinstance checks.
    # all numeric numpy dtypes subclass np.integer / np.floating, so test those
    # (and include the builtin types for completeness).
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return str(value)


def row_to_dict(row, valid_cols=None):
    if valid_cols is None:
        return {col: serialize_value(val) for col, val in row.items()}
    return {col: serialize_value(row[col]) for col in valid_cols if col in row}



def generate_new_pk_value(df, pk_col, index):
    """
    Generate a new primary key value based on the column's data type.
    """
    existing_values = df[pk_col].dropna()

    if len(existing_values) == 0:
        return f"NEW_{index+1}"

    sample_value = str(existing_values.iloc[0])

    # Pattern 1: Pure numeric IDs
    if sample_value.isdigit():
        existing_numeric = existing_values.astype(str).str.extract(r'(\d+)')[0].astype(int)
        max_id = existing_numeric.max()
        return str(max_id + index + 1)

    # Pattern 2: Prefix + numeric
    match = re.match(r'([A-Za-z]+)(\d+)', sample_value)
    if match:
        prefix = match.group(1)
        numeric_part = match.group(2)
        padding = len(numeric_part)

        all_numbers = []
        for val in existing_values:
            val_str = str(val)
            num_match = re.search(r'(\d+)', val_str)
            if num_match:
                try:
                    all_numbers.append(int(num_match.group(1)))
                except ValueError:
                    continue

        if all_numbers:
            max_num = max(all_numbers)
            new_num = max_num + index + 1
            return f"{prefix}{str(new_num).zfill(padding)}"
        else:
            return f"{prefix}{str(index+1).zfill(padding)}"

    # Pattern 3: UUID or complex string
    return f"{sample_value}_NEW_{index+1}"


def generate_insert_scenarios(df, valid_cols, count, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    for i in range(min(count, len(df))):
        row = df.iloc[i]

        scenario = {
            "scenario_id": str(uuid.uuid4()),
            "operation": "INSERT",
            "before_image": {},
            "after_image": row_to_dict(row, valid_cols),
            "executable": True,
        }

        with open(outdir / f"insert_{i}.json", "w") as f:
            json.dump(scenario, f, indent=2)



def generate_update_scenarios(df, num_rows, pk_columns, output_dir="scenarios/updates"):
    """
    Generate UPDATE scenarios - one JSON file per row.
    """
    os.makedirs(output_dir, exist_ok=True)

    generated_files = []

    print(f"\nGenerating {num_rows} UPDATE scenarios...")

    sample_indices = random.sample(range(len(df)), min(num_rows, len(df)))

    for idx, row_idx in enumerate(sample_indices):
        row = df.iloc[row_idx]

        pk_dict = {pk_col: serialize_value(row[pk_col]) for pk_col in pk_columns}

        updatable_columns = [col for col in df.columns if col not in pk_columns]

        if not updatable_columns:
            print(f"  No updatable columns found, skipping...")
            continue

        col_to_update = random.choice(updatable_columns)

        before_image = row_to_dict(row)
        after_image = before_image.copy()

        original_value = row[col_to_update]

        if pd.api.types.is_numeric_dtype(df[col_to_update]):
            if pd.notna(original_value):
                change_pct = random.uniform(-0.5, 0.5)
                new_value = original_value * (1 + change_pct)
                after_image[col_to_update] = serialize_value(new_value)
            else:
                non_null = df[col_to_update].dropna()
                if len(non_null) > 0:
                    after_image[col_to_update] = serialize_value(random.choice(non_null))

        elif pd.api.types.is_datetime64_any_dtype(df[col_to_update]):
            if pd.notna(original_value):
                days_shift = random.randint(-30, 30)
                new_value = pd.to_datetime(original_value) + timedelta(days=days_shift)
                after_image[col_to_update] = serialize_value(new_value)

        else:
            other_values = df[df[col_to_update] != original_value][col_to_update].dropna().unique()
            if len(other_values) > 0:
                new_value = random.choice(other_values)
                after_image[col_to_update] = serialize_value(new_value)
            else:
                after_image[col_to_update] = serialize_value(f"{original_value}_UPDATED")

        scenario = {
            **pk_dict,
            "date_of_generation": datetime.now().strftime('%Y-%m-%d'),
            "operation": "UPDATE",
            "updated_column": col_to_update,
            "before_image": before_image,
            "after_image": after_image
        }

        pk_values = "_".join([f"{k}_{str(v).replace('/', '_')}" for k, v in pk_dict.items()])
        filename = f"update_{pk_values}_{idx+1}.json"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'w') as f:
            json.dump(scenario, f, indent=2)

        generated_files.append(filepath)
        print(f"  Created: {filename} (Updated: {col_to_update})")

    return generated_files


def generate_delete_scenarios(df, num_rows, pk_columns, output_dir="scenarios/deletes"):
    """
    Generate DELETE scenarios - one JSON file per row.
    """
    os.makedirs(output_dir, exist_ok=True)

    generated_files = []

    print(f"\nGenerating {num_rows} DELETE scenarios...")

    sample_indices = random.sample(range(len(df)), min(num_rows, len(df)))

    for idx, row_idx in enumerate(sample_indices):
        row = df.iloc[row_idx]

        pk_dict = {pk_col: serialize_value(row[pk_col]) for pk_col in pk_columns}

        before_image = row_to_dict(row)

        scenario = {
            **pk_dict,
            "date_of_generation": datetime.now().strftime('%Y-%m-%d'),
            "operation": "DELETE",
            "before_image": before_image,
            "after_image": {}
        }

        pk_values = "_".join([f"{k}_{str(v).replace('/', '_')}" for k, v in pk_dict.items()])
        filename = f"delete_{pk_values}_{idx+1}.json"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'w') as f:
            json.dump(scenario, f, indent=2)

        generated_files.append(filepath)
        print(f"  Created: {filename}")

    return generated_files


def generate_scenario_files(df, num_inserts=2, num_updates=2, num_deletes=1,
                           pk_columns=None, base_output_dir="scenarios"):
    """
    Generate separate JSON files for INSERT, UPDATE, DELETE operations.
    """
    print(f"\n{'='*60}")
    print(f"GENERATING SCENARIO FILES")
    print(f"{'='*60}")
    print(f"Source DataFrame: {len(df)} rows, {len(df.columns)} columns")

    if pk_columns is None:
        pk_columns = identify_primary_keys(df, "result_df")

    os.makedirs(base_output_dir, exist_ok=True)

    results = {
        "metadata": {
            "total_source_rows": len(df),
            "primary_keys": pk_columns,
            "generation_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "base_output_dir": base_output_dir
        },
        "file_counts": {
            "inserts": num_inserts,
            "updates": num_updates,
            "deletes": num_deletes,
            "total": num_inserts + num_updates + num_deletes
        },
        "generated_files": {
            "inserts": [],
            "updates": [],
            "deletes": []
        }
    }

    if num_inserts > 0:
        insert_dir = os.path.join(base_output_dir, "inserts")
        results["generated_files"]["inserts"] = generate_insert_scenarios(
            df, num_inserts, pk_columns, insert_dir
        )

    if num_updates > 0:
        update_dir = os.path.join(base_output_dir, "updates")
        results["generated_files"]["updates"] = generate_update_scenarios(
            df, num_updates, pk_columns, update_dir
        )

    if num_deletes > 0:
        delete_dir = os.path.join(base_output_dir, "deletes")
        results["generated_files"]["deletes"] = generate_delete_scenarios(
            df, num_deletes, pk_columns, delete_dir
        )

    summary_file = os.path.join(base_output_dir, "scenario_summary.json")
    with open(summary_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"GENERATION COMPLETE")
    print(f"{'='*60}")
    print(f"Output directory: {base_output_dir}")
    print(f"INSERT files: {len(results['generated_files']['inserts'])}")
    print(f"UPDATE files: {len(results['generated_files']['updates'])}")
    print(f"DELETE files: {len(results['generated_files']['deletes'])}")
    print(f"Total files: {results['file_counts']['total']}")
    print(f"Summary saved to: {summary_file}")

    return results


def _resolve_target_column_value(rule: str, row: dict, df_columns: list) -> Any:
    import re
    from datetime import datetime

    # ---------------------------------------------------------
    # ✅ Normalize logic
    # ---------------------------------------------------------
    rule = normalize_logic(rule)

    if not rule or rule.strip().lower() in ("", "nan", "none"):
        return None

    rule_stripped = rule.strip()

    # ---------------------------------------------------------
    # ✅ SYSTEM GENERATED
    # ---------------------------------------------------------
    if rule_stripped.upper() == 'SYSTEM' or any(kw in rule_stripped.upper() for kw in ['CURRENT_TIMESTAMP', 'SYSDATE', 'GETDATE', 'NOW']):
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

  
    # ---------------------------------------------------------
    # ✅ CLEAN CASE HANDLING
    # ---------------------------------------------------------
    case_match = re.match(
    r"CASE WHEN (\w+)\s*([><=]+)\s*(\w+)\s*THEN\s*'?(\w+)'?\s*ELSE\s*'?(\w+)'?",
    rule_stripped,
    re.IGNORECASE
    )

    if case_match:
        col = case_match.group(1)
        op = case_match.group(2)
        val = case_match.group(3)
        true_val = case_match.group(4)
        false_val = case_match.group(5)

        actual = _find_row_value(row, col)
        compare_val = _find_row_value(row, val)

        if compare_val is None:
            compare_val = val

        try:
            actual = float(actual)
            compare_val = float(compare_val)

            if op == ">" and actual > compare_val:
                return true_val.upper()
            elif op == "<" and actual < compare_val:
                return true_val.upper()
            elif op == "=" and actual == compare_val:
                return true_val.upper()
            else:
                return false_val.upper()

        except:
         return false_val.upper()


    # ---------------------------------------------------------
    # ✅ DIRECT COLUMN (T.COL)
    # ---------------------------------------------------------
    direct_match = re.match(
        r'^([A-Z][A-Z0-9]{0,9})\.([A-Z_][A-Z0-9_]*)$',
    rule_stripped,
    re.IGNORECASE
    )

    if direct_match:
        col_name = direct_match.group(2)
        return _find_row_value(row, col_name)


    # ---------------------------------------------------------
    # ✅ SIMPLE ARITHMETIC WITH ALIAS
    # ---------------------------------------------------------
    arith_pattern = r'^([A-Z][A-Z0-9]{0,9})\.(\w+)\s*([*+\-/])\s*([A-Z][A-Z0-9]{0,9})\.(\w+)$'
    arith_match = re.match(arith_pattern, rule_stripped, re.IGNORECASE)

    if arith_match:
        col1 = arith_match.group(2)
        op = arith_match.group(3)
        col2 = arith_match.group(5)

        val1 = _find_row_value(row, col1)
        val2 = _find_row_value(row, col2)

        if val1 is not None and val2 is not None:
            try:
                v1 = float(val1)
                v2 = float(val2)

                if op == '*':
                 return round(v1 * v2, 2)
                elif op == '+':
                    return round(v1 + v2, 2)
                elif op == '-':
                    return round(v1 - v2, 2)
                elif op == '/' and v2 != 0:
                    return round(v1 / v2, 2)

            except:
                return None


    # ---------------------------------------------------------
    # ✅ SIMPLE ARITHMETIC WITHOUT ALIAS
    # Supports: QTY * PRICE, LINE_AMOUNT / QTY
     # ---------------------------------------------------------
    simple_arith = re.match(
    r'^(\w+)\s*([*+\-/])\s*(\w+)$',
    rule_stripped,
    re.IGNORECASE
    )

    if simple_arith:
        col1 = simple_arith.group(1)
        op = simple_arith.group(2)
        col2 = simple_arith.group(3)

        val1 = _find_row_value(row, col1)
        val2 = _find_row_value(row, col2)

        if val1 is not None and val2 is not None:
           try:
              v1 = float(val1)
              v2 = float(val2)

              if op == '*':
                return round(v1 * v2, 2)
              elif op == '+':
                return round(v1 + v2, 2)
              elif op == '-':
                return round(v1 - v2, 2)
              elif op == '/' and v2 != 0:
                return round(v1 / v2, 2)

           except:
            return None


     # ---------------------------------------------------------
     # ✅ GENERIC COLUMN REFERENCE (IMPORTANT: before plain)
     # ---------------------------------------------------------
    col_refs = re.findall(
    r'([A-Z][A-Z0-9]{0,9})\.([A-Z_]\w*)',
    rule_stripped,
    re.IGNORECASE
   )

    if col_refs:
      for _, col_name in col_refs:
        val = _find_row_value(row, col_name)
        if val is not None:
            return val


   # ---------------------------------------------------------
   # ✅ PLAIN COLUMN (LAST STEP)
   # ---------------------------------------------------------
    if re.match(r'^[A-Z_][A-Z0-9_]*$', rule_stripped, re.IGNORECASE):
      val = _find_row_value(row, rule_stripped)
      if val is not None:
        return val
    # ---------------------------------------------------------
    # ✅ GENERIC COLUMN REFERENCE
    # ---------------------------------------------------------
    col_refs = re.findall(
        r'([A-Z][A-Z0-9]{0,9})\.([A-Z_]\w*)',
        rule_stripped,
        re.IGNORECASE
    )

    if col_refs:
        for _, col_name in col_refs:
            val = _find_row_value(row, col_name)
            if val is not None:
                return val

    # ---------------------------------------------------------
    # ✅ LOOKUP / DIRECT
    # ---------------------------------------------------------
    if rule_stripped.lower() in ("direct mapping", "direct", "1:1", "pass-through"):
        return None

    lookup_match = re.match(
        r'(?:lookup|from|via|enriched?\s+from)\s+(\w+)',
        rule_stripped,
        re.IGNORECASE
    )

    if lookup_match:
        return None

    # ---------------------------------------------------------
    # ✅ FINAL FALLBACK
    # ---------------------------------------------------------
    return _find_row_value(row, rule_stripped)
   


def _find_row_value(row: dict, col_name: str) -> Any:

    if not col_name:
        return None

    # direct match
    if col_name in row:
        return row[col_name]

    col_upper = col_name.upper()
    col_norm = normalize_column_name(col_name)

    # ✅ exact match (case-insensitive)
    for k in row:
        if k.upper() == col_upper:
            return row[k]

    # ✅ normalized match
    for k in row:
        if normalize_column_name(k) == col_norm:
            return row[k]

    # ❌ REMOVE partial match completely
    # This was causing CUSTOMER_NAME → CUSTOMER_ID issue

    return None



def _suffix_column_match(row: dict, target_col: str) -> Any:
    """
    Generic fallback: find a source column whose normalized name is a suffix
    of the normalized target column name.

    Examples:
      ORDER_STATUS  → STATUS   (orderstatus ends with status)
      UNIT_PRICE    → PRICE    (unitprice ends with price)
      PAYMENT_AMOUNT → AMOUNT  (paymentamount ends with amount)

    Picks the longest match to avoid short false-positives (e.g. 'ID').
    Skips columns that are join artifacts (contain _SRC_ or _REF_).
    """
    target_norm = target_col.replace('_', '').lower()
    best_val = None
    best_len = 0

    for k, v in row.items():
        if v is None:
            continue
        k_upper = k.upper()
        if '_SRC_' in k_upper or '_REF_' in k_upper:
            continue
        k_norm = k.replace('_', '').lower()
        if len(k_norm) >= 3 and target_norm.endswith(k_norm) and len(k_norm) > best_len:
            best_val = v
            best_len = len(k_norm)

    return best_val


def _build_target_row(row: dict, target_columns: dict, pk_cols: list) -> dict:
    """
    Build a target-column-only row from a source row using the mapping rules.

    Args:
        row: dict from joined result_df (all source columns)
        target_columns: dict mapping target_col_name → transformation_rule
        pk_cols: list of business key column names (target-side)

    Returns:
        dict with target column names as keys
    """
    target_row = {}


    for target_col, rule in target_columns.items():

        # ---------------------------------------------------------
        # ✅ Step 1: resolve using transformation logic
        # ---------------------------------------------------------
        value = _resolve_target_column_value(rule, row, list(row.keys()))

        # DEBUG (keep for now)
        print(f"👉 {target_col} | rule={rule} | resolved={value}")

        # ---------------------------------------------------------
        # ✅ Step 2: fallback - direct match
        # ---------------------------------------------------------
        if value is None:
            value = _find_row_value(row, target_col)

        # ---------------------------------------------------------
        # ✅ Step 3: fallback - exact name match only
        # ---------------------------------------------------------
        if value is None:
            for col in row:
                if target_col.lower() == col.lower():
                    value = row[col]
                    break

        # ---------------------------------------------------------
        # ✅ Step 4: fallback - stripped names
        # ---------------------------------------------------------
        if value is None:
            stripped = (
                target_col
                .replace("_NAME", "")
                .replace("_DESC", "")
                .replace("_CD", "")
            )
            if stripped != target_col:
                value = _find_row_value(row, stripped)

        # ---------------------------------------------------------
        # ✅ Step 4b: fallback - suffix match
        # Handles cases where the source column is a suffix of the
        # target column name, e.g. ORDER_STATUS→STATUS, UNIT_PRICE→PRICE
        # ---------------------------------------------------------
        if value is None:
            value = _suffix_column_match(row, target_col)

        # ---------------------------------------------------------
        # ✅ Step 5: assign + derived chaining (CRITICAL)
        # ---------------------------------------------------------
        if value is not None:
            target_row[target_col] = serialize_value(value)

            # 🔥 REQUIRED: allow derived columns to reuse this
            row[target_col] = value

    # ---------------------------------------------------------
    # ✅ Step 6: ensure business keys
    # ---------------------------------------------------------
    for pk in pk_cols:
        if pk not in target_row:
            val = _find_row_value(row, pk)
            if val is not None:
                target_row[pk] = serialize_value(val)

    # ---------------------------------------------------------
    # ✅ Step 7: ensure all columns exist
    # ---------------------------------------------------------
    for col in target_columns:
        if col not in target_row:
            target_row[col] = None

    return target_row



 #------------ Update existing scenarios--------------------------------   
def merge_update_scenarios(existing_scenarios, result_df, pk_cols):
    updated = []
    new_scenarios = []

    # Build lookup from existing scenarios
    existing_lookup = {}
    for sc in existing_scenarios:
        key = tuple(sc.get(pk) for pk in pk_cols)
        existing_lookup[key] = sc

    for _, row in result_df.iterrows():
        key = tuple(row.get(pk) for pk in pk_cols)

        if key in existing_lookup:
            # 🔄 UPDATE EXISTING
            sc = existing_lookup[key]

            sc["after_image"] = {
                col: row.get(col)
                for col in sc.get("after_image", {}).keys()
            }

            sc["updated"] = True
            updated.append(sc)

        else:
            # 🆕 CREATE NEW
            new_scenarios.append({
                "scenario_id": str(uuid.uuid4()),
                "operation": "INSERT",
                "after_image": row.to_dict(),
                "created_new": True
            })

    return updated, new_scenarios




def build_target_scenarios(mapping_path, target_meta=None, output_dir=None):

    print("\nBuilding target scenarios...")
    print(mapping_path)

    mapping = build_sql_mapping(mapping_path)

    # =============================================
    # EXECUTION LOG — tracks everything for gap analysis
    # =============================================
    execution_log = {
        "source_tables": {
            "expected": mapping["source_tables"],
            "loaded": [],
            "missing": [],
        },
        "joins": [],          # per-join tracking
        "filters": [],        # per-filter tracking
        "target_columns": [], # per-column tracking
        "deduplication": {},
        "scenarios_generated": {},
        "row_counts": {},
    }

    # -----------------------------
    # LOAD DATAFRAMES
    # -----------------------------
    dfs = {}
    for t in mapping["source_tables"]:
        p = Path(PROFILER_DIR) / f"{t}_profiled.csv"
        if not p.exists():
            p = Path(REFERENCE_DIR) / f"{t}.csv"
        if not p.exists():
            p = Path(SAMPLE_DIR) / f"{t}_sample.csv"
        if not p.exists():
            p = Path(SAMPLE_DIR) / f"{t}.csv"

        if not p.exists():
            execution_log["source_tables"]["missing"].append(t)
            raise FileNotFoundError(
                f"Source table '{t}' not found. Looked in:\n"
                f"  - {Path(PROFILER_DIR) / f'{t}_profiled.csv'}\n"
                f"  - {Path(REFERENCE_DIR) / f'{t}.csv'}\n"
                f"  - {Path(SAMPLE_DIR) / f'{t}_sample.csv'}\n"
                f"  - {Path(SAMPLE_DIR) / f'{t}.csv'}\n"
                "Upload and profile the raw data first."
            )
        dfs[t] = pd.read_csv(p)
        execution_log["source_tables"]["loaded"].append({
            "table": t,
            "rows": len(dfs[t]),
            "columns": len(dfs[t].columns),
        })

    # Store initial row counts per table
    for t, df in dfs.items():
        execution_log["row_counts"][t] = len(df)

    # -----------------------------
    # JOIN (with tracking)
    # -----------------------------
    join_pairs = extract_join_pairs_advanced(mapping["joins"])

    # Track each join defined in mapping
    for idx, join_cfg in enumerate(mapping["joins"]):
        join_entry = {
            "index": idx,
            "type": join_cfg.get("type", "INNER"),
            "sql": join_cfg.get("sql", "")[:120],
            "keys": join_cfg.get("keys", []),
            "status": "pending",
            "rows_before": None,
            "rows_after": None,
            "rows_dropped": 0,
            "rows_added": 0,
            "risk": "none",
            "note": "",
        }
        execution_log["joins"].append(join_entry)

    if join_pairs:
        counter = Counter()
        for l, _, r, _ in join_pairs:
            counter[l] += 1
            counter[r] += 1

        driving = counter.most_common(1)[0][0]
        print(f"Driving table: {driving}")

        dfs = force_join_compatibility_sequential(dfs, join_pairs, driving)

        # --- Track join execution row-by-row ---
        # We need to intercept the join process to log per-join metrics.
        # Do a manual tracked join instead of calling join_dataframes_with_resolution.
        resolved_pairs = resolve_join_pairs(join_pairs, dfs)

        result_df = dfs[driving].copy()
        joined_tables = {driving}
        execution_log["row_counts"]["driving_table"] = len(result_df)
        execution_log["row_counts"]["driving_table_name"] = driving

        join_idx = 0
        for left_table, left_key, right_table, right_key in resolved_pairs:
            join_type = 'inner'
            matched_join_idx = None

            # Find matching join config entry
            for cfg_idx, config in enumerate(mapping["joins"]):
                if config['type'] == 'LEFT' and right_table in config['sql']:
                    join_type = 'left'
                    matched_join_idx = cfg_idx
                    break
                elif config['type'] == 'RIGHT' and right_table in config['sql']:
                    join_type = 'right'
                    matched_join_idx = cfg_idx
                    break
                elif right_table in config['sql']:
                    matched_join_idx = cfg_idx
                    break

            if matched_join_idx is None:
                matched_join_idx = min(join_idx, len(execution_log["joins"]) - 1)

            if left_table in joined_tables and right_table not in joined_tables:
                before_rows = len(result_df)

                result_df = result_df.merge(
                    dfs[right_table],
                    left_on=left_key,
                    right_on=right_key,
                    how=join_type,
                    suffixes=('', f'_{right_table}')
                )

                joined_tables.add(right_table)
                after_rows = len(result_df)

                # Update execution log for this join
                if matched_join_idx < len(execution_log["joins"]):
                    entry = execution_log["joins"][matched_join_idx]
                    entry["status"] = "executed"
                    entry["rows_before"] = before_rows
                    entry["rows_after"] = after_rows
                    entry["rows_dropped"] = max(0, before_rows - after_rows)
                    entry["rows_added"] = max(0, after_rows - before_rows)
                    entry["tables_joined"] = f"{left_table} ↔ {right_table}"
                    entry["keys_used"] = f"{left_key} = {right_key}"

                    # Classify risk
                    if join_type == 'inner' and after_rows < before_rows:
                        drop_pct = round((before_rows - after_rows) / before_rows * 100, 1)
                        entry["risk"] = "high" if drop_pct > 20 else "medium"
                        entry["note"] = f"INNER JOIN dropped {drop_pct}% rows ({before_rows}→{after_rows})"
                    elif join_type == 'left' and after_rows > before_rows:
                        mult = round(after_rows / before_rows, 1)
                        entry["risk"] = "medium" if mult > 2 else "low"
                        entry["note"] = f"LEFT JOIN caused {mult}x row explosion ({before_rows}→{after_rows})"
                    elif join_type == 'left' and after_rows == before_rows:
                        entry["risk"] = "none"
                        entry["note"] = "LEFT JOIN: rows preserved (1:1 match)"
                    else:
                        entry["risk"] = "none"
                        entry["note"] = f"{join_type.upper()} JOIN: {before_rows}→{after_rows}"

                print(f"  {join_type.upper()} JOIN {right_table}: {before_rows} → {after_rows}")

            join_idx += 1

        # Mark any un-executed joins
        for entry in execution_log["joins"]:
            if entry["status"] == "pending":
                entry["status"] = "not_executed"
                entry["risk"] = "high"
                entry["note"] = "JOIN defined in mapping but NOT executed — table data may be missing"

    else:
        # Single-table scenario (no joins)
        driving = list(dfs.keys())[0] if dfs else None
        if driving:
            result_df = dfs[driving].copy()
            print(f"Single-table scenario: using {driving} ({len(result_df)} rows)")
        else:
            raise ValueError("No source tables loaded — cannot build scenarios")

    if result_df is None or result_df.empty:
        raise ValueError(
            f"No data after joining source tables. "
            f"Tables loaded: {list(dfs.keys())}, Join pairs: {len(join_pairs)}"
        )

    execution_log["row_counts"]["after_joins"] = len(result_df)
    print(f"\nJoined result rows: {len(result_df)}")
    MAX_SCENARIOS = 5

    if result_df is not None and len(result_df) > MAX_SCENARIOS:
        print(f"⚡ Limiting result_df to {MAX_SCENARIOS} rows for demo")
    result_df = result_df.head(MAX_SCENARIOS)

    # -----------------------------
    # TARGET NAME & KEYS
    # -----------------------------
    if target_meta:
        target_table = target_meta["table"]
        pk_cols = target_meta.get("business_keys", [])
    else:
        target_table = mapping.get("target_table", "TARGET_TABLE")
        pk_cols = mapping.get("business_keys", [])

    if not pk_cols:
        pk_cols = identify_primary_keys(result_df, "result")

    # -----------------------------
    # TARGET COLUMN MAPPING (with tracking)
    # Get target_columns from mapping to build proper scenario images
    # -----------------------------
    target_columns = mapping.get("target_columns", {})

    if target_columns:
        print(f"\nTarget columns from mapping ({len(target_columns)}):")
        for tc, rule in target_columns.items():
            print(f"  {tc} = {rule[:60]}{'...' if len(str(rule)) > 60 else ''}")

    # Track target column resolution
    if target_columns:
        sample_row = result_df.iloc[0].to_dict() if len(result_df) > 0 else {}
        for tc, rule in target_columns.items():
            val = _resolve_target_column_value(rule, sample_row, list(sample_row.keys()))
            if val is None:
                val = _find_row_value(sample_row, tc)

            # Classify the transformation type
            rule_upper = str(rule).upper().strip()
            if "CASE" in rule_upper and "WHEN" in rule_upper:
                xform_type = "CASE/WHEN"
            elif re.search(r'[*+\-/]', rule):
                xform_type = "Calculation"
            elif re.match(r'^[A-Z][A-Z0-9]{0,9}\.\w+$', rule.strip(), re.IGNORECASE):
                xform_type = "Direct reference"
            elif rule.strip().lower() in ("direct mapping", "direct", "1:1"):
                xform_type = "Direct mapping"
            elif re.match(r'(?:lookup|from|via)', rule.strip(), re.IGNORECASE):
                xform_type = "Lookup/Enrichment"
            elif any(kw in rule_upper for kw in ('CURRENT_TIMESTAMP', 'SYSDATE', 'NOW')):
                xform_type = "System generated"
            else:
                xform_type = "Complex/Other"

            execution_log["target_columns"].append({
                "column": tc,
                "rule": str(rule)[:100],
                "type": xform_type,
                "resolved": val is not None,
                "sample_value": str(val)[:50] if val is not None else None,
                "status": "covered" if val is not None else "gap",
            })

    # Track filter application
    for filt in mapping.get("filters", []):
        # Filters were applied during join phase or not at all
        # Check if the filter condition references columns in result_df
        filt_cols = re.findall(r'[A-Z][A-Z0-9]{0,9}\.(\w+)', str(filt), re.IGNORECASE)
        cols_found = []
        for fc in filt_cols:
            m = find_matching_column(fc, result_df.columns.tolist(), "result")
            if m:
                cols_found.append(m)

        execution_log["filters"].append({
            "expression": str(filt)[:120],
            "columns_referenced": filt_cols,
            "columns_found_in_data": cols_found,
            "testable": len(cols_found) == len(filt_cols) and len(filt_cols) > 0,
            "status": "covered" if cols_found else "gap",
            "note": "All filter columns present in data" if len(cols_found) == len(filt_cols) and filt_cols
                    else "Filter columns NOT found — cannot validate this filter" if not cols_found
                    else f"Partial: {len(cols_found)}/{len(filt_cols)} columns found",
        })

    # -----------------------------
    # DEDUPLICATE after LEFT JOINs
    # Left joins can cause row explosion (10 → 138 rows).
    # Deduplicate on business keys to get unique rows.
    # -----------------------------
    if pk_cols and len(result_df) > 0:
        dedup_cols = []
        for pk in pk_cols:
            matched = find_matching_column(pk, result_df.columns.tolist(), "result")
            if matched:
                dedup_cols.append(matched)

        if dedup_cols:
            before_dedup = len(result_df)
            result_df = result_df.drop_duplicates(subset=dedup_cols, keep='first')
            after_dedup = len(result_df)
            execution_log["deduplication"] = {
                "keys": dedup_cols,
                "before": before_dedup,
                "after": after_dedup,
                "removed": before_dedup - after_dedup,
            }
            if before_dedup != after_dedup:
                print(f"\nDeduplicated on {dedup_cols}: {before_dedup} → {after_dedup} rows")
        else:
            print(f"\nWarning: Could not find dedup columns for {pk_cols} in result_df")

    execution_log["row_counts"]["final"] = len(result_df)
    print(f"Final result rows: {len(result_df)}")

    # -----------------------------
    # SCENARIO DIR
    # -----------------------------
    if output_dir:
        scenario_dir = Path(output_dir)
    else:
        scenario_dir = Path(SCENARIOS_DIR) / target_table

    scenario_dir.mkdir(parents=True, exist_ok=True)

    inserts_dir = scenario_dir / "insert"
    updates_dir = scenario_dir / "update"
    deletes_dir = scenario_dir / "delete"

    inserts_dir.mkdir(parents=True, exist_ok=True)
    updates_dir.mkdir(parents=True, exist_ok=True)
    deletes_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------
    # Helper: build scenario row with target columns only
    # -----------------------------
    def make_target_row(source_row: dict) -> dict:
        """Convert a joined source row to target-column-only row."""
        if target_columns:
            return _build_target_row(source_row, target_columns, pk_cols)
        else:
            return {k: serialize_value(v) for k, v in source_row.items()
                    if not _is_internal_column(k)}

    # -----------------------------
    # BUILD INSERT
    # -----------------------------
    num_inserts = min(10, len(result_df))
    for i in range(num_inserts):

        row = result_df.iloc[i].to_dict()
        target_row = make_target_row(row)

        
        scenario = {
        "scenario_id": str(uuid.uuid4()),
        "target_table": target_table,
        "business_keys": pk_cols,
        "operation": "INSERT",
        "before_image": {},
        "after_image": target_row,

     # 🔥 CRITICAL FOR AI
         "metadata": {
        "joins": mapping.get("joins", []),
        "filters": mapping.get("filters", []),
        "target_columns": list(target_columns.keys()) if target_columns else []
        }
    }

        with open(inserts_dir / f"insert_{i}.json", "w") as f:
            json.dump(scenario, f, indent=2, default=str)

    # -----------------------------
    # BUILD UPDATE
    # -----------------------------
    num_updates = min(10, len(result_df))
    for i in range(num_updates):

        row = result_df.iloc[i].to_dict()
        before = make_target_row(row)
        after = before.copy()

        for c in after:
            if c not in pk_cols and "id" not in c.lower():
                val = after[c]
                if isinstance(val, (int, float)):
                    after[c] = round(val * 1.1, 2)
                elif isinstance(val, str) and val:
                    after[c] = val + "_UPDATED"
                break

        scenario = {
    "scenario_id": str(uuid.uuid4()),
    "target_table": target_table,
    "business_keys": pk_cols,
    "operation": "UPDATE",
    "before_image": before,
    "after_image": after,

    "metadata": {
        "joins": mapping.get("joins", []),
        "filters": mapping.get("filters", []),
        "target_columns": list(target_columns.keys()) if target_columns else []
    }
}

        with open(updates_dir / f"update_{i}.json", "w") as f:
            json.dump(scenario, f, indent=2, default=str)

    # -----------------------------
    # BUILD DELETE
    # -----------------------------
    num_deletes = min(5, len(result_df))
    for i in range(num_deletes):

        row = result_df.iloc[i].to_dict()
        target_row = make_target_row(row)

        scenario = {
        "scenario_id": str(uuid.uuid4()),
    "target_table": target_table,
    "business_keys": pk_cols,
    "operation": "DELETE",
    "before_image": target_row,
    "after_image": {},

     "metadata": {
        "joins": mapping.get("joins", []),
        "filters": mapping.get("filters", []),
        "target_columns": list(target_columns.keys()) if target_columns else []
    }
}
        with open(deletes_dir / f"delete_{i}.json", "w") as f:
            json.dump(scenario, f, indent=2, default=str)

    total = num_inserts + num_updates + num_deletes
    execution_log["scenarios_generated"] = {
    "inserts": num_inserts,
    "updates": num_updates,
    "deletes": num_deletes,
    "total": total,
}

    # 🔥 ADD HERE
    execution_log["scenario_dir"] = str(scenario_dir)
    execution_log["version"] = "v2"

    execution_log["coverage"] = {
    "joins_total": len(mapping.get("joins", [])),
    "filters_total": len(mapping.get("filters", [])),
    "columns_total": len(target_columns)
}

    # =============================================
    # 🚀 DEMO MODE LIMIT (HARDCODED)
    # =============================================
    MAX_SCENARIOS = 5

    if result_df is not None and len(result_df) > MAX_SCENARIOS:
        print(f"⚡ Limiting scenarios to {MAX_SCENARIOS} for demo")
        result_df = result_df.head(MAX_SCENARIOS)
    
    print(f"\nGenerated {total} scenarios in {scenario_dir}")

    return result_df, scenario_dir, execution_log