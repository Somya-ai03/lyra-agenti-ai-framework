# core/snowflake/target_validation.py
import os
import snowflake.connector
from cryptography.hazmat.primitives import serialization
import pandas as pd
from typing import Dict, Any, List, Optional


# -------------------------------------------------
# Snowflake connection
# -------------------------------------------------

   


def snowflake_connection():

    with open("lyra_key.p8", "rb") as key:
        p_key = serialization.load_pem_private_key(
            key.read(),
            password=None,
        )

    private_key = p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    return snowflake.connector.connect(
        user=os.environ["SNOWFLAKE_USER"],
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        private_key=private_key,
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"),
        database=os.environ.get("SNOWFLAKE_DATABASE"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA"),
    )
    


def execute_query(sql: str, database: str, schema: str) -> pd.DataFrame:
    conn = snowflake_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetch_pandas_all()
    finally:
        conn.close()


def execute_query_params(sql: str, params: list, database: str, schema: str) -> pd.DataFrame:
    conn = snowflake_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetch_pandas_all()
    finally:
        conn.close()


# -------------------------------------------------
# Column normalizer
# camelCase → SNOWFLAKE_CASE
# -------------------------------------------------
def normalize(col: str) -> str:
    """
    camelCase → CAMEL_CASE
    TradeId → TRADE_ID
    counterpartyId → COUNTERPARTY_ID
    CURRENCY_CODE → CURRENCY_CODE  (already snake_case, no change)
    ORDER_ID → ORDER_ID
    Trade_Id → TRADE_ID
    """
    if not col:
        return col

    col = col.replace(" ", "").replace("-", "_")

    # If already UPPER_SNAKE_CASE or has underscores, just return uppercase
    if col == col.upper() or "_" in col:
        return col.upper()

    # Convert camelCase / PascalCase → SNAKE_CASE
    new = col[0]
    for i, c in enumerate(col[1:], 1):
        if c.isupper() and col[i - 1].islower():
            new += "_" + c
        else:
            new += c

    return new.upper()


# -------------------------------------------------
# Internal column detection
# Columns to exclude: join artifacts from scenario generation
# -------------------------------------------------
def _is_internal_column(col: str) -> bool:
    """
    Return True for columns that are internal join artifacts, not real target columns.
    """
    upper = col.upper()

    # Columns like RecordId_SRC_POSITIONS, variance_SRC_COUNTERPARTY
    if "_SRC_" in upper:
        return True

    # Columns named exactly 'variance' or scenario variance artifacts
    if upper == "VARIANCE" or (
        upper.startswith("VARIANCE_") and
        any(x in upper for x in ("_SRC_", "_TYPE", "_VALUE"))
    ):
        return True

    # RecordId is usually a row-number artifact
    if upper in ("RECORD_ID", "RECORDID"):
        return True

    return False


# -------------------------------------------------
# Fetch actual column names from Snowflake
# -------------------------------------------------
_column_cache: Dict[str, List[str]] = {}


def _get_real_columns(database: str, schema: str, table: str) -> List[str]:
    """
    Query Snowflake INFORMATION_SCHEMA to get the actual column names
    for a target table. Results are cached per table.
    """
    cache_key = f"{database}.{schema}.{table}"
    if cache_key in _column_cache:
        return _column_cache[cache_key]

    try:
        sql = f"""
            SELECT COLUMN_NAME
            FROM {database}.INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = '{schema}'
              AND TABLE_NAME = '{table}'
            ORDER BY ORDINAL_POSITION
        """
        df = execute_query(sql, database, schema)
        cols = df["COLUMN_NAME"].tolist() if not df.empty else []
        _column_cache[cache_key] = cols
        return cols
    except Exception:
        return []


def _map_to_real_column(
    normalized_name: str,
    real_columns: List[str],
) -> Optional[str]:
    """
    Find the actual Snowflake column name that matches our normalized name.

    Matching priority:
      1. Exact match (case-insensitive)
      2. Normalized match (normalize both sides and compare)
      3. Stripped-underscore match (TRADE_ID matches TRADEID)
    """
    if not real_columns:
        return normalized_name  # fallback: use as-is

    norm_upper = normalized_name.upper()
    norm_stripped = norm_upper.replace("_", "")

    for rc in real_columns:
        rc_upper = rc.upper()

        # 1. Exact match
        if rc_upper == norm_upper:
            return rc

        # 2. Normalized match
        if normalize(rc) == norm_upper:
            return rc

        # 3. Stripped-underscore match (TRADEID == TRADE_ID)
        if rc_upper.replace("_", "") == norm_stripped:
            return rc

    return None  # no match found


# -------------------------------------------------
# Smart business key detection
# -------------------------------------------------
def _smart_detect_business_keys(
    scenario_upper: dict,
    target_columns: Optional[List[str]] = None,
) -> dict:
    """
    Smart fallback to detect business keys from scenario columns.

    Priority:
      1. _ID columns that also exist in target_columns (if provided)
      2. All _ID columns (excluding internal), capped at 3
      3. First non-internal column as last resort
    """
    key_values = {}

    # Collect candidate _ID columns, excluding internal ones
    id_candidates = {}
    for k, v in scenario_upper.items():
        if _is_internal_column(k):
            continue
        if k.endswith("_ID") or k == "ID":
            id_candidates[k] = v

    if id_candidates:
        # If we have target_columns info, prefer keys that exist in the target
        if target_columns:
            target_set = {c.upper() for c in target_columns}
            # Also add normalized versions for matching
            target_normalized = {normalize(c) for c in target_columns}
            target_stripped = {c.upper().replace("_", "") for c in target_columns}

            matched = {}
            for k, v in id_candidates.items():
                if k in target_set or k in target_normalized or k.replace("_", "") in target_stripped:
                    matched[k] = v

            if matched:
                for i, (k, v) in enumerate(matched.items()):
                    if i >= 3:
                        break
                    key_values[k] = v
                return key_values

        # No target_columns filter: use the first _ID column
        first_key = next(iter(id_candidates))
        key_values[first_key] = id_candidates[first_key]
        return key_values

    # Last resort: first non-internal column
    for k, v in scenario_upper.items():
        if not _is_internal_column(k):
            key_values[k] = v
            return key_values

    return key_values

#------------------------------------------------
def _prepare_valid_row(data, database, schema, table):
    real_columns = _get_real_columns(database, schema, table)

    clean = {}

    for k, v in data.items():

        if _is_internal_column(k):
            continue

        normalized = normalize(k)

        real_col = _map_to_real_column(normalized, real_columns)

        if real_col:
            clean[real_col] = v

    return clean

#--------------------------------------------------------

def execute_scenario(scenario, target_meta):

    conn = snowflake_connection()
    cursor = conn.cursor()

    database = target_meta["database"]
    schema = target_meta["schema"]
    table_name = target_meta["table"]

    table = f"{database}.{schema}.{table_name}"

    operation = scenario.get("operation", "").upper()
    before = scenario.get("before_image", {}) or {}
    after = scenario.get("after_image", {}) or {}

    # Normalize keys
    before = {normalize(k): v for k, v in before.items()}
    after = {normalize(k): v for k, v in after.items()}

    # -----------------------------------
    # SQL formatter
    # -----------------------------------
    def format_sql_value(v):
        if v is None:
            return "NULL"
        if isinstance(v, (int, float)):
            return str(v)
        return f"'{str(v)}'"

    # -----------------------------------
    # Business keys
    # -----------------------------------
    pk_cols = target_meta.get("business_keys", [])

    if not pk_cols:
        scenario_upper = {k.upper(): v for k, v in {**before, **after}.items()}
        detected = _smart_detect_business_keys(scenario_upper)
        pk_cols = list(detected.keys())

    # -----------------------------------
    # WHERE using PK
    # -----------------------------------
    def build_pk_condition(source):
        conditions = []
        for col in pk_cols:
            val = source.get(col)
            if val is not None:
                conditions.append(f'"{col}"={format_sql_value(val)}')
        return " AND ".join(conditions)

    # -----------------------------------
    # INSERT
    # -----------------------------------
    if operation == "INSERT" and after:

        after["IS_LATEST"] = True
        after["IS_DELETED"] = False

        clean_after = _prepare_valid_row(after, database, schema, table_name)

        if not clean_after:
            return

        cols = ", ".join([f'"{c}"' for c in clean_after.keys()])
        values = ", ".join([format_sql_value(v) for v in clean_after.values()])

        sql = f"""
            INSERT INTO {table} ({cols})
            VALUES ({values})
        """

        print("INSERT SQL:", sql)
        cursor.execute(sql)

    # -----------------------------------
    # UPDATE (CDC)
    # -----------------------------------
    elif operation == "UPDATE" and after:

        clean_after = _prepare_valid_row(after, database, schema, table_name)

        if not clean_after:
            return

        where_clause = build_pk_condition(clean_after)

        # expire old record
        cursor.execute(f"""
            UPDATE {table}
            SET IS_LATEST = FALSE
            WHERE {where_clause} AND IS_LATEST = TRUE
        """)

        # insert new version
        clean_after["IS_LATEST"] = True
        clean_after["IS_DELETED"] = False

        cols = ", ".join([f'"{c}"' for c in clean_after.keys()])
        values = ", ".join([format_sql_value(v) for v in clean_after.values()])

        sql = f"""
            INSERT INTO {table} ({cols})
            VALUES ({values})
        """

        print("UPDATE INSERT SQL:", sql)
        cursor.execute(sql)

    # -----------------------------------
    # DELETE (CDC SOFT DELETE)
    # -----------------------------------
    elif operation == "DELETE" and before:

        clean_before = _prepare_valid_row(before.copy(), database, schema, table_name)

        if not clean_before:
            return

        where_clause = build_pk_condition(clean_before)

        # expire old
        cursor.execute(f"""
            UPDATE {table}
            SET IS_LATEST = FALSE
            WHERE {where_clause} AND IS_LATEST = TRUE
        """)

        # insert deleted version
        clean_before["IS_LATEST"] = True
        clean_before["IS_DELETED"] = True

        cols = ", ".join([f'"{c}"' for c in clean_before.keys()])
        values = ", ".join([format_sql_value(v) for v in clean_before.values()])

        sql = f"""
            INSERT INTO {table} ({cols})
            VALUES ({values})
        """

        print("DELETE INSERT SQL:", sql)
        cursor.execute(sql)

    conn.commit()
    cursor.close()
    conn.close()

# -------------------------------------------------
# MAIN VALIDATION
# -------------------------------------------------
def validate_scenario(
    scenario: Dict[str, Any],
    target_meta: Dict[str, Any]
) -> Dict[str, Any]:

    database = target_meta["database"]
    schema = target_meta["schema"]
    table = target_meta["table"]

   

    # Business keys: prefer target_meta, fallback to scenario-embedded keys
    business_keys = target_meta.get("business_keys", [])
    if not business_keys:
        business_keys = scenario.get("business_keys", [])

    # Target columns (for smart detection filtering)
    target_columns = target_meta.get("columns", [])

    full_table = f"{database}.{schema}.{table}"

    operation = scenario.get("operation", "").upper()

    # --------------------------------------
    # Expected values
    # --------------------------------------
    if operation == "DELETE":
        expected = scenario.get("before_image", {})
    else:
        expected = scenario.get("after_image", {})

    if not expected:
        return {"status": "SKIPPED", "reason": "No expected values"}

    # --------------------------------------
    # Filter out internal columns from expected
    # --------------------------------------
    clean_expected = {k: v for k, v in expected.items() if not _is_internal_column(k)}

    if not clean_expected:
        return {"status": "SKIPPED", "reason": "No valid columns after filtering artifacts"}

    # --------------------------------------
    # Get actual Snowflake column names
    # This ensures we use the REAL column names, not our guesses
    # --------------------------------------
    real_columns = _get_real_columns(database, schema, table)

    # --------------------------------------
    # Map scenario keys to real Snowflake column names
    # --------------------------------------
    scenario_mapped = {}
    for k, v in clean_expected.items():
        normalized = normalize(k)
        if real_columns:
            real_col = _map_to_real_column(normalized, real_columns)
            if real_col:
                scenario_mapped[real_col] = v
            # else: skip columns not in the target table
        else:
            # No real columns info: use normalized name (old behavior)
            scenario_mapped[normalized] = v

    if not scenario_mapped:
        return {"status": "SKIPPED", "reason": "No scenario columns match target table"}

    # --------------------------------------
    # Resolve business key names to real column names
    # --------------------------------------
    business_keys_resolved = []
    for bk in business_keys:
        normalized = normalize(bk)
        if real_columns:
            real_col = _map_to_real_column(normalized, real_columns)
            if real_col:
                business_keys_resolved.append(real_col)
        else:
            business_keys_resolved.append(normalized)

    # --------------------------------------
    # Extract business key values
    # --------------------------------------
    key_values = {}

    for k in business_keys_resolved:
        if k in scenario_mapped:
            key_values[k] = scenario_mapped[k]

    # Fallback: smart detection from mapped scenario columns
    if not key_values:
        # Build an uppercase version for detection
        scenario_upper = {k.upper(): v for k, v in scenario_mapped.items()}
        real_cols_for_detect = real_columns if real_columns else target_columns
        detected = _smart_detect_business_keys(scenario_upper, real_cols_for_detect)
        # Map detected keys back to real column names
        for dk, dv in detected.items():
            if real_columns:
                real_col = _map_to_real_column(dk, real_columns)
                if real_col:
                    key_values[real_col] = dv
                else:
                    key_values[dk] = dv
            else:
                key_values[dk] = dv

    if not key_values:
        return {
            "status": "SKIPPED",
            "reason": "Business keys missing in scenario",
            "pk": None,
            "mismatches": []
        }

    # --------------------------------------
    # Build parameterized WHERE clause
    # (safe from SQL injection)
    # --------------------------------------
    conditions = [f"\"{k}\" = %s" for k in key_values]
    params = list(key_values.values())
    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT *
        FROM {full_table}
        WHERE {where_clause}
        And IS_LATEST = TRUE
    """

    try:
        df = execute_query_params(sql, params, database, schema)
    except Exception as e:
        return {
            "status": "ERROR",
            "reason": f"Snowflake query failed: {str(e)}",
            "pk": key_values,
            "mismatches": [],
            "sql": sql,
        }

    # --------------------------------------
    # DELETE validation
    # --------------------------------------
    if operation == "DELETE":

        if df.empty:
            return {
            "status": "FAIL",
            "pk": key_values,
            "reason": "Row missing — cannot validate delete",
            "mismatches": []
        }

        row = df.iloc[0].to_dict()

        is_deleted = str(row.get("IS_DELETED", "")).upper()
        is_latest = str(row.get("IS_LATEST", "")).upper()

        if is_deleted in ("TRUE", "1") or is_latest in ("FALSE", "0"):
            return {
            "status": "PASS",
            "pk": key_values,
            "mismatches": []
        }

        return {
          "status": "FAIL",
        "pk": key_values,
        "reason": "Row still active (delete not applied)",
        "mismatches": [],
        "rows_found": len(df),
         }

    # --------------------------------------
    # INSERT / UPDATE validation
    # --------------------------------------
    if df.empty:
        return {
            "status": "FAIL",
            "pk": key_values,
            "reason": "Row not found in target",
            "mismatches": []
        }

    # Use first matched row
    row = {k: v for k, v in df.iloc[0].to_dict().items()}

    mismatches = []

    for col, expected_val in scenario_mapped.items():

        # Find this column in the result row (case-insensitive)
        actual_val = None
        matched_col = None
        for row_col in row:
            if row_col.upper() == col.upper():
                actual_val = row[row_col]
                matched_col = row_col
                break

        if matched_col is None:
            continue  # column not in target table

        # Flexible comparison
        if not _values_match(actual_val, expected_val):
            mismatches.append({
                "column": col,
                "expected": expected_val,
                "actual": actual_val
            })

    if mismatches:
        return {
            "status": "FAIL",
            "pk": key_values,
            "mismatches": mismatches
        }

    return {
        "status": "PASS",
        "pk": key_values,
        "mismatches": []
    }

    


def validate_scenario_debug(
    scenario: Dict[str, Any],
    target_meta: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Debug version of validate_scenario that returns full diagnostic info
    including intermediate steps, SQL, column mappings, and Snowflake response.
    """
    debug = {}

    database = target_meta["database"]
    schema = target_meta["schema"]
    table = target_meta["table"]

    debug["target_meta"] = target_meta
    debug["full_table"] = f"{database}.{schema}.{table}"

    # Business keys
    business_keys = target_meta.get("business_keys", [])
    if not business_keys:
        business_keys = scenario.get("business_keys", [])
    debug["business_keys_source"] = "target_meta" if target_meta.get("business_keys") else "scenario"
    debug["business_keys_raw"] = business_keys

    target_columns = target_meta.get("columns", [])
    operation = scenario.get("operation", "").upper()
    debug["operation"] = operation

    # Expected values
    if operation == "DELETE":
        expected = scenario.get("before_image", {})
    else:
        expected = scenario.get("after_image", {})

    debug["expected_columns_raw"] = list(expected.keys()) if expected else []

    # Filter internal
    clean_expected = {k: v for k, v in expected.items() if not _is_internal_column(k)}
    debug["clean_expected_columns"] = list(clean_expected.keys())

    # Get real columns
    real_columns = _get_real_columns(database, schema, table)
    debug["real_snowflake_columns"] = real_columns

    # Map scenario keys to real names
    scenario_mapped = {}
    column_mapping_detail = []
    for k, v in clean_expected.items():
        normalized = normalize(k)
        if real_columns:
            real_col = _map_to_real_column(normalized, real_columns)
            if real_col:
                scenario_mapped[real_col] = v
                column_mapping_detail.append({"scenario": k, "normalized": normalized, "snowflake": real_col, "matched": True})
            else:
                column_mapping_detail.append({"scenario": k, "normalized": normalized, "snowflake": None, "matched": False})
        else:
            scenario_mapped[normalized] = v
            column_mapping_detail.append({"scenario": k, "normalized": normalized, "snowflake": normalized, "matched": "no_real_cols"})

    debug["column_mapping"] = column_mapping_detail
    debug["scenario_mapped_columns"] = list(scenario_mapped.keys())

    # Resolve business keys
    business_keys_resolved = []
    bk_detail = []
    for bk in business_keys:
        normalized = normalize(bk)
        if real_columns:
            real_col = _map_to_real_column(normalized, real_columns)
            if real_col:
                business_keys_resolved.append(real_col)
                bk_detail.append({"raw": bk, "normalized": normalized, "resolved": real_col})
            else:
                bk_detail.append({"raw": bk, "normalized": normalized, "resolved": None, "ERROR": "NOT FOUND in Snowflake"})
        else:
            business_keys_resolved.append(normalized)
            bk_detail.append({"raw": bk, "normalized": normalized, "resolved": normalized})

    debug["business_key_resolution"] = bk_detail

    # Extract key values
    key_values = {}
    for k in business_keys_resolved:
        if k in scenario_mapped:
            key_values[k] = scenario_mapped[k]

    if not key_values:
        scenario_upper = {k.upper(): v for k, v in scenario_mapped.items()}
        detected = _smart_detect_business_keys(scenario_upper, real_columns or target_columns)
        for dk, dv in detected.items():
            if real_columns:
                real_col = _map_to_real_column(dk, real_columns)
                key_values[real_col or dk] = dv
            else:
                key_values[dk] = dv
        debug["key_detection"] = "fallback_smart_detect"
    else:
        debug["key_detection"] = "from_business_keys"

    debug["key_values"] = key_values

    if not key_values:
        debug["result"] = "SKIPPED - no keys"
        return debug

    # Build SQL
    conditions = [f"\"{k}\" = %s" for k in key_values]
    params = list(key_values.values())
    where_clause = " AND ".join(conditions)

    sql = f"SELECT * FROM {database}.{schema}.{table} WHERE {where_clause}"
    debug["sql"] = sql
    debug["sql_params"] = params

    # Execute
    try:
        df = execute_query_params(
            f"SELECT * FROM {database}.{schema}.{table} WHERE {where_clause}",
            params, database, schema
        )
        debug["rows_returned"] = len(df)
        debug["snowflake_columns"] = list(df.columns) if not df.empty else []

        if not df.empty:
            # Show first row
            first_row = {k: str(v) for k, v in df.iloc[0].to_dict().items()}
            debug["first_row"] = first_row

            # Column-by-column comparison
            row = {k: v for k, v in df.iloc[0].to_dict().items()}
            comparisons = []
            for col, expected_val in scenario_mapped.items():
                actual_val = None
                for row_col in row:
                    if row_col.upper() == col.upper():
                        actual_val = row[row_col]
                        break

                match = _values_match(actual_val, expected_val) if actual_val is not None else None
                comparisons.append({
                    "column": col,
                    "expected": str(expected_val),
                    "actual": str(actual_val) if actual_val is not None else "NOT IN ROW",
                    "match": match,
                    "expected_type": type(expected_val).__name__,
                    "actual_type": type(actual_val).__name__ if actual_val is not None else "N/A",
                })

            debug["comparisons"] = comparisons
            debug["mismatches"] = [c for c in comparisons if c["match"] is False]

    except Exception as e:
        debug["query_error"] = str(e)

    # Run the actual validation too
    result = validate_scenario(scenario, target_meta)
    debug["validation_result"] = result

    return debug


def _values_match(actual, expected) -> bool:
    """
    Flexible value comparison that handles type mismatches
    between Snowflake results and scenario data.
    """
    # Both None/NaN
    if actual is None and expected is None:
        return True
    if actual is not None and not isinstance(actual, str):
        try:
            if pd.isna(actual):
                return expected is None or (not isinstance(expected, str) and pd.isna(expected))
        except (ValueError, TypeError):
            pass

    # Direct equality
    if actual == expected:
        return True

    # String comparison (covers most cases)
    str_actual = str(actual).strip()
    str_expected = str(expected).strip()

    if str_actual == str_expected:
        return True

    # Case-insensitive string comparison
    if str_actual.upper() == str_expected.upper():
        return True

    # Numeric comparison (123 vs 123.0)
    try:
        if float(str_actual) == float(str_expected):
            return True
    except (ValueError, TypeError):
        pass

    # Boolean comparison
    if str_actual.lower() in ('true', 'false') and str_expected.lower() in ('true', 'false'):
        return str_actual.lower() == str_expected.lower()

    return False