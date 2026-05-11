import re
from core.snowflake.target_validation import execute_query, normalize



def resolve_target_metadata(database, schema, table, mapping):
    """
    SAFE resolver:
    - does NOT query Snowflake PK tables
    - uses mapping joins as business keys
    """

    # -------------------------
    # 1. Target columns from mapping
    # -------------------------
    target_columns = list(mapping.get("target_columns", {}).keys())
    columns = [c.upper() for c in target_columns]

    # -------------------------
    # 2. Business keys from joins
    # -------------------------
    business_keys = set()

    for join in mapping.get("joins", []):
        sql = join.get("sql", "")
        # Match alias.COLUMN patterns (e.g. T.TradeId, OL.ORDER_ID)
        matches = re.findall(r"\b[A-Za-z]{1,10}\.(\w+)\b", sql)

        for col in matches:
            col_upper = col.upper()
            # Also try normalizing camelCase → UPPER_SNAKE_CASE
            col_normalized = normalize(col)
            if col_upper in columns:
                business_keys.add(col_upper)
            elif col_normalized in columns:
                business_keys.add(col_normalized)

        # Also extract keys from join "keys" list
        for key_pair in join.get("keys", []):
            if isinstance(key_pair, dict):
                for side in ["left", "right", "source", "target"]:
                    if side in key_pair:
                        k = key_pair[side].upper()
                        if k in columns:
                            business_keys.add(k)
            elif isinstance(key_pair, str):
                k = key_pair.upper()
                if k in columns:
                    business_keys.add(k)

    # fallback → any ID column from target columns
    if not business_keys:
        business_keys = [c for c in columns if c.endswith("ID") or c.endswith("_ID")]

    # If still nothing, try to find the first column with "ID" in its name
    if not business_keys:
        business_keys = [c for c in columns if "ID" in c][:1]

    print("JOIN KEYS FROM MAPPING:", mapping.get("joins", []))
    print("BUSINESS KEYS DERIVED:", business_keys)


    # -------------------------
    return {
        "database": database,
        "schema": schema,
        "table": table,
        "columns": columns,
        "business_keys": sorted(business_keys),
        "cdc": {
            "is_latest_column": None,
            "is_deleted_column": None
        }

    }