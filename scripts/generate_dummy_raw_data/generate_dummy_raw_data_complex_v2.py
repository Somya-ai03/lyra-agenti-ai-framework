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
NUM_CUSTOMERS = 2_000_000
NUM_PRODUCTS = 2_000_000
NUM_ORDERS = 5_000_000
NUM_LINES = 1_000_000
NUM_PAYMENTS = 1_000_000

CHUNK = 200_000

# ============================================
# REF TABLES (still smaller)
# ============================================
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

# ============================================
# CUSTOMERS (3M)
# ============================================
print("Generating CUSTOMERS...")

cust_file = RAW_DIR/"SRC_CUSTOMERS.csv"
if cust_file.exists(): cust_file.unlink()

for start in range(0, NUM_CUSTOMERS, CHUNK):
    end = min(start+CHUNK, NUM_CUSTOMERS)
    size = end-start

    df = pd.DataFrame({
        "CUSTOMER_ID":[f"CUST{i:08}" for i in range(start,end)],
        "CUSTOMER_NAME":[f"Customer_{i}" for i in range(start,end)],
        "REGION_CODE":np.random.choice(region_codes,size),
        "STATUS":np.random.choice(["ACTIVE","INACTIVE"],size,p=[0.9,0.1])
    })

    df.to_csv(cust_file,mode="a",index=False,header=not cust_file.exists())
    print(f"Customers {end}/{NUM_CUSTOMERS}")

print("Customers done")

# ============================================
# PRODUCTS (2M)
# ============================================
print("Generating PRODUCTS...")

prod_file = RAW_DIR/"SRC_PRODUCTS.csv"
if prod_file.exists(): prod_file.unlink()

for start in range(0, NUM_PRODUCTS, CHUNK):
    end = min(start+CHUNK, NUM_PRODUCTS)
    size = end-start

    df = pd.DataFrame({
        "PRODUCT_ID":[f"PROD{i:08}" for i in range(start,end)],
        "PRODUCT_NAME":[f"Product_{i}" for i in range(start,end)],
        "PRICE":np.random.randint(5,5000,size),
        "CATEGORY":np.random.choice(["A","B","C","D"],size)
    })

    df.to_csv(prod_file,mode="a",index=False,header=not prod_file.exists())
    print(f"Products {end}/{NUM_PRODUCTS}")

print("Products done")

# Load IDs for joins
customer_ids = [f"CUST{i:08}" for i in range(NUM_CUSTOMERS)]
product_ids = [f"PROD{i:08}" for i in range(NUM_PRODUCTS)]

# ============================================
# ORDERS (5M)
# ============================================
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

# ============================================
# ORDER LINES (15M)
# ============================================
print("Generating ORDER LINES...")

lines_file = RAW_DIR/"SRC_ORDER_LINES.csv"
if lines_file.exists(): lines_file.unlink()

for start in range(0, NUM_LINES, CHUNK):
    end = min(start+CHUNK, NUM_LINES)
    size = end-start

    df = pd.DataFrame({
        "LINE_ID":[f"LINE{i:010}" for i in range(start,end)],
        "ORDER_ID":np.random.choice(order_ids,size),
        "PRODUCT_ID":np.random.choice(product_ids,size),
        "QTY":np.random.randint(1,5,size),
        "LINE_AMOUNT":np.random.randint(10,2000,size)
    })

    df.to_csv(lines_file,mode="a",index=False,header=not lines_file.exists())
    print(f"Lines {end}/{NUM_LINES}")

print("Lines done")

# ============================================
# PAYMENTS (5M)
# ============================================
print("Generating PAYMENTS...")

pay_file = RAW_DIR/"SRC_PAYMENTS.csv"
if pay_file.exists(): pay_file.unlink()

for start in range(0, NUM_PAYMENTS, CHUNK):
    end = min(start+CHUNK, NUM_PAYMENTS)
    size = end-start

    df = pd.DataFrame({
        "PAYMENT_ID":[f"PAY{i:09}" for i in range(start,end)],
        "ORDER_ID":np.random.choice(order_ids,size),
        "AMOUNT":np.random.randint(50,5000,size),
        "PAYMENT_STATUS":np.random.choice(["PAID","FAILED","PENDING"],size,p=[0.7,0.1,0.2])
    })

    df.to_csv(pay_file,mode="a",index=False,header=not pay_file.exists())
    print(f"Payments {end}/{NUM_PAYMENTS}")

print("\n🔥 ULTRA MASSIVE DATA GENERATION COMPLETE")
