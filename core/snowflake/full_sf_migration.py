import os
import pandas as pd

from dotenv import load_dotenv

from sqlalchemy import create_engine
from snowflake.sqlalchemy import URL

from cryptography.hazmat.primitives import serialization

print("🔥 Migration Script Started")

# =====================================================
# LOAD ENV
# =====================================================

load_dotenv()


# =====================================================
# LOAD PRIVATE KEY
# =====================================================

with open("/Users/somyak/projects/lyra-agentic-ai-framework/lyra_key.p8", "rb") as key:

    p_key = serialization.load_pem_private_key(
        key.read(),
        password=None,
    )

private_key = p_key.private_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)


# =====================================================
# OLD SNOWFLAKE ENGINE
# =====================================================

old_engine = create_engine(
    URL(
        account=os.environ["OLD_SNOWFLAKE_ACCOUNT"],
        user=os.environ["OLD_SNOWFLAKE_USER"],
        database=os.environ["OLD_SNOWFLAKE_DATABASE"],
        schema="TARGET",
        warehouse=os.environ["OLD_SNOWFLAKE_WAREHOUSE"],
    ),
    connect_args={
        "private_key": private_key
    }
)


# =====================================================
# NEW SNOWFLAKE ENGINE
# =====================================================
print("\nNEW SF ENV CHECK")

print(os.environ.get("SNOWFLAKE_ACCOUNT"))
print(os.environ.get("SNOWFLAKE_USER"))
print(os.environ.get("SNOWFLAKE_DATABASE"))



new_engine = create_engine(
    URL(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=os.environ["SNOWFLAKE_SCHEMA"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        role=os.environ["SNOWFLAKE_ROLE"],
    )
)


# =====================================================
# GET TABLES
# =====================================================

table_query = """
SELECT TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'TARGET'
"""

tables = pd.read_sql(table_query, old_engine)

print("\nTables Found:")
print(tables)


# =====================================================
# MIGRATE TABLES
# =====================================================
test = pd.read_sql(
    "SELECT CURRENT_DATABASE(), CURRENT_SCHEMA()",
    new_engine
)

print(test)

for table in tables["table_name"]:

    print(f"\n{'='*60}")
    print(f"Migrating: {table}")
    print(f"{'='*60}")

    try:

        # -----------------------------------------
        # READ OLD TABLE
        # -----------------------------------------

        query = f"SELECT * FROM TARGET.{table}"

        df = pd.read_sql(query, old_engine)

        print(f"Rows: {len(df)}")

        # -----------------------------------------
        # WRITE TO NEW SF
        # -----------------------------------------

        df.to_sql(
            table,
            new_engine,
            schema="TARGET",
            if_exists="replace",
            index=False,
            method="multi",
            chunksize=10000
        )

        print(f"✅ SUCCESS: {table}")

    except Exception as e:

        print(f"❌ FAILED: {table}")
        print(str(e))


print("\n🔥 TARGET MIGRATION COMPLETE")