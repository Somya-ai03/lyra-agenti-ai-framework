import os
import snowflake.connector
import json
from typing import Optional
from cryptography.hazmat.primitives import serialization


def get_conn(database: Optional[str] = None, schema: Optional[str] = None):

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
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "DEV_WH"),
        database=database or os.environ.get("SNOWFLAKE_DATABASE", "AI_TEST"),
        schema=schema or os.environ.get("SNOWFLAKE_SCHEMA", "TARGET"),
        role=os.getenv("SNOWFLAKE_ROLE")
    )


def execute_insert(cur, table, after_image):
    cols = list(after_image.keys())
    vals = [after_image[c] for c in cols]

    col_str = ",".join(cols)
    placeholder = ",".join(["%s"] * len(vals))

    sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholder})"
    cur.execute(sql, vals)


def execute_update(cur, table, pk_dict, after_image):
    set_cols = []
    set_vals = []

    for col, val in after_image.items():
        if col not in pk_dict:
            set_cols.append(f"{col}=%s")
            set_vals.append(val)

    where_clause = " AND ".join([f"{k}=%s" for k in pk_dict])
    where_vals = list(pk_dict.values())

    sql = f"""
    UPDATE {table}
    SET {",".join(set_cols)}
    WHERE {where_clause}
    """

    cur.execute(sql, set_vals + where_vals)


def execute_delete(cur, table, pk_dict):
    where_clause = " AND ".join([f"{k}=%s" for k in pk_dict])
    vals = list(pk_dict.values())

    sql = f"DELETE FROM {table} WHERE {where_clause}"
    cur.execute(sql, vals)


def execute_scenario(scenario, target_table):
    conn = get_conn()
    cur = conn.cursor()

    operation = scenario["operation"]
    after_image = scenario.get("after_image", {})
    before_image = scenario.get("before_image", {})

    pk_dict = {
        k: v for k, v in scenario.items()
        if k not in ["scenario_id","operation","before_image","after_image","executable"]
    }

    try:
        if operation == "INSERT":
            execute_insert(cur, target_table, after_image)

        elif operation == "UPDATE":
            execute_update(cur, target_table, pk_dict, after_image)

        elif operation == "DELETE":
            execute_delete(cur, target_table, pk_dict)

        conn.commit()
        status = "EXECUTED"

    except Exception as e:
        conn.rollback()
        print("Execution error:", e)
        status = "ERROR"

    cur.close()
    conn.close()
    return status