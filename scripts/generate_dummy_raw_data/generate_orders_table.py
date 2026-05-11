import pandas as pd
import numpy as np
from pathlib import Path
import random
from datetime import datetime, timedelta

BASE_DIR = Path("keyrus_agentic_testing_framework/data_profiler_tool/data")
RAW_DIR = BASE_DIR / "raw"
REF_DIR = RAW_DIR / "reference_tables"

RAW_DIR.mkdir(parents=True, exist_ok=True)
REF_DIR.mkdir(parents=True, exist_ok=True)

np.random.seed(42)
random.seed(42)

# ============================================
# CONFIG (ULTRA SCALE)
# ============================================

NUM_ORDERS = 2_000_000
CHUNK = 200_000


print("Generating REF tables")

regions = pd.DataFrame({
    "REGION_CODE":["APAC","EMEA","NA"],
    "REGION_NAME":["Asia","Europe","North America"]
})
regions.to_csv(REF_DIR/"REF_REGION.csv",index=False)

currency = pd.DataFrame({
    "CURRENCY_CODE":["USD","EUR","INR","JPY"],
    "CURRENCY_RATE":[1,0.9,82,110]
})
currency.to_csv(REF_DIR/"REF_CURRENCY.csv",index=False)

promo = pd.DataFrame({
    "PROMO_CODE":[f"P{i:03}" for i in range(100)],
    "DISCOUNT_PCT":np.random.randint(5,40,100)
})
promo.to_csv(REF_DIR/"REF_PROMOTION.csv",index=False)

currency_codes = currency["CURRENCY_CODE"].values
region_codes = regions["REGION_CODE"].values
promo_codes = promo["PROMO_CODE"].values





print("Generating ORDERS...")

orders_file = RAW_DIR/"SRC_ORDERS.csv"
if orders_file.exists(): orders_file.unlink()

for start in range(0, NUM_ORDERS, CHUNK):
    end = min(start+CHUNK, NUM_ORDERS)
    size = end-start

    df = pd.DataFrame({
        "ORDER_ID":[f"ORD{i:09}" for i in range(start,end)],
        "CUSTOMER_ID":np.random.choice(customer_ids,size),
        "ORDER_DATE":[datetime(2024,1,1)+timedelta(days=random.randint(0,365)) for _ in range(size)],
        "STATUS":np.random.choice(["OPEN","CLOSED","CANCELLED"],size,p=[0.6,0.3,0.1]),
        "CURRENCY_CODE":np.random.choice(currency_codes,size),
        "PROMO_CODE":np.random.choice(promo_codes,size)
    })

    df.to_csv(orders_file,mode="a",index=False,header=not orders_file.exists())
    print(f"Orders {end}/{NUM_ORDERS}")

print("Orders done")

order_ids = [f"ORD{i:09}" for i in range(NUM_ORDERS)]