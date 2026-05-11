import os
import pandas as pd
from pathlib import Path
from datetime import datetime

from core.snowflake.target_validation import snowflake_connection


# -------------------------------------------------
# PATHS
# -------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = PROJECT_ROOT / "data" / "raw"
REF_DIR = RAW_DIR / "reference_tables"


# -------------------------------------------------
# ENV
# -------------------------------------------------

DATABASE = os.getenv("SNOWFLAKE_DATABASE", "AI_TEST")
SOURCE_SCHEMA = os.getenv("SNOWFLAKE_SOURCE_SCHEMA", "SOURCE")
WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE", "DEV_WH")


# -------------------------------------------------
# TABLE EXISTS
# -------------------------------------------------

def table_exists(cursor, table, schema):

    sql = f"""
    SELECT COUNT(*)
    FROM {DATABASE}.INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = '{schema}'
    AND TABLE_NAME = '{table.upper()}'
    """

    cursor.execute(sql)
    return cursor.fetchone()[0] > 0


# -------------------------------------------------
# GET EXISTING COLUMNS
# -------------------------------------------------

def get_existing_columns(cursor, table, schema):

    sql = f"""
    SELECT COLUMN_NAME
    FROM {DATABASE}.INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = '{schema}'
    AND TABLE_NAME = '{table.upper()}'
    """

    cursor.execute(sql)
    return {r[0] for r in cursor.fetchall()}


# -------------------------------------------------
# INFER TYPE
# -------------------------------------------------

def infer_snowflake_type(series):

    if pd.api.types.is_integer_dtype(series):
        return "NUMBER"

    if pd.api.types.is_float_dtype(series):
        return "FLOAT"

    if pd.api.types.is_datetime64_any_dtype(series):
        return "TIMESTAMP"

    return "STRING"


# -------------------------------------------------
# CREATE TABLE
# -------------------------------------------------

def create_table(cursor, table, df, schema):

    cols = []

    for col in df.columns:
        dtype = infer_snowflake_type(df[col])
        cols.append(f"{col} {dtype}")

    cols_sql = ", ".join(cols)

    sql = f"""
    CREATE TABLE IF NOT EXISTS {DATABASE}.{schema}.{table} (
        {cols_sql}
    )
    """

    print(f"🆕 Creating table → {schema}.{table}")
    cursor.execute(sql)


# -------------------------------------------------
# SCHEMA SNAPSHOT
# -------------------------------------------------

def store_schema_snapshot(cursor, table, schema, version_tag):

    sql = f"""
    SELECT COLUMN_NAME, DATA_TYPE
    FROM {DATABASE}.INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = '{schema}'
    AND TABLE_NAME = '{table.upper()}'
    """

    cursor.execute(sql)
    rows = cursor.fetchall()

    now = datetime.now()

    values = [
        f"('{table}','{schema}','{col}','{dtype}','{now}','{version_tag}')"
        for col, dtype in rows
    ]

    if values:
        cursor.execute(f"""
        INSERT INTO SCHEMA_HISTORY
        (TABLE_NAME, SCHEMA_NAME, COLUMN_NAME, DATA_TYPE, VERSION_TS, VERSION_TAG)
        VALUES {",".join(values)}
        """)

        print(f"🧾 Snapshot stored → {schema}.{table} ({version_tag})")


# -------------------------------------------------
# SCHEMA COMPARE
# -------------------------------------------------

def compare_schema(cursor, table, df, schema):

    existing = get_existing_columns(cursor, table, schema)

    csv_cols = {c.upper() for c in df.columns}
    snow_cols = {c.upper() for c in existing}

    missing_in_sf = csv_cols - snow_cols

    print(f"\n🔎 Schema check → {schema}.{table}")

    if missing_in_sf:
        print("⚠ Missing in Snowflake:", missing_in_sf)
    else:
        print("✅ Schemas match")

    return missing_in_sf


# -------------------------------------------------
# ADD COLUMNS
# -------------------------------------------------

def add_missing_columns(cursor, table, df, cols, schema):

    for col in cols:

        dtype = infer_snowflake_type(df[col])

        sql = f"""
        ALTER TABLE {DATABASE}.{schema}.{table}
        ADD COLUMN {col} {dtype}
        """

        print(f"🧩 Adding column {col} → {schema}.{table}")
        cursor.execute(sql)


# -------------------------------------------------
# LOAD DATA
# -------------------------------------------------

def load_data(cursor, table, df, schema):

    tmp_file = f"/tmp/{table}.csv"
    df.to_csv(tmp_file, index=False)

    stage = f"%{table}"

    cursor.execute(f"PUT file://{tmp_file} @{stage} OVERWRITE=TRUE")

    cols = ",".join(df.columns)

    cursor.execute(f"TRUNCATE TABLE {DATABASE}.{schema}.{table}")

    cursor.execute(f"""
        COPY INTO {DATABASE}.{schema}.{table} ({cols})
        FROM @{stage}
        FILE_FORMAT = (
            TYPE = CSV
            SKIP_HEADER = 1
            FIELD_OPTIONALLY_ENCLOSED_BY = '"'
        )
    """)

    print(f"⬆️ Loaded data → {schema}.{table}")


# -------------------------------------------------
# PROCESS SOURCE FILE
# -------------------------------------------------

def process_source_file(path, cursor):

    table = path.stem
    print(f"\n📦 Processing SOURCE → {table}")

    df = pd.read_csv(path)

    if not table_exists(cursor, table, SOURCE_SCHEMA):

        create_table(cursor, table, df, SOURCE_SCHEMA)
        store_schema_snapshot(cursor, table, SOURCE_SCHEMA, "V1")

    else:

        store_schema_snapshot(cursor, table, SOURCE_SCHEMA, "BEFORE")

        missing = compare_schema(cursor, table, df, SOURCE_SCHEMA)

        if missing:
            add_missing_columns(cursor, table, df, missing, SOURCE_SCHEMA)

        store_schema_snapshot(cursor, table, SOURCE_SCHEMA, "AFTER")

    load_data(cursor, table, df, SOURCE_SCHEMA)


# -------------------------------------------------
# MAIN SYNC (CLEANED)
# -------------------------------------------------

def sync_all_tables():

    conn = snowflake_connection()
    cursor = conn.cursor()

    cursor.execute(f"USE WAREHOUSE {WAREHOUSE}")
    cursor.execute(f"USE DATABASE {DATABASE}")
    cursor.execute(f"USE SCHEMA {SOURCE_SCHEMA}")

    print("\n☁️ Syncing SOURCE...")

    for path in RAW_DIR.glob("*.csv"):
        process_source_file(path, cursor)

    for path in REF_DIR.glob("*.csv"):
        process_source_file(path, cursor)

    conn.commit()
    cursor.close()
    conn.close()

    print("\n✅ SOURCE SYNC COMPLETE")