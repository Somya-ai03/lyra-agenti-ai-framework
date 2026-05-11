import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import os
from pathlib import Path
# -----------------------------
# CONFIG
# -----------------------------
N_ORDERS = 1_000_000
N_LINES = 2_000_000
N_CUSTOMERS = 200_000
N_PRODUCTS = 100_000
N_PAYMENTS = 1_000_000
N_REF = 50_000

# -------------------------------------------------
# PATH SETUP
# -------------------------------------------------

PROJECT_ROOT = Path("/Users/somyak/projects/My-AI-project/lyra-agentic-ai-framework")

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
REF_DIR = RAW_DIR / "reference_tables"

RAW_DIR.mkdir(parents=True, exist_ok=True)
REF_DIR.mkdir(parents=True, exist_ok=True)
# -----------------------------
# HELPERS
# -----------------------------
def random_date(start, end):
    delta = end - start
    return start + timedelta(days=random.randint(0, delta.days))

start_date = datetime(2020, 1, 1)
end_date = datetime(2025, 12, 31)

# -----------------------------
# REF TABLES
# -----------------------------

print("Generating REF tables...")

ref_region = pd.DataFrame({
    "REGION_CODE": [f"R{i}" for i in range(N_REF)],
    "REGION_NAME": [f"Region_{i}" for i in range(N_REF)]
})

ref_currency = pd.DataFrame({
    "CURRENCY_CODE": [f"C{i}" for i in range(N_REF)],
    "CURRENCY_NAME": [f"Currency_{i}" for i in range(N_REF)]
})

ref_region.to_csv(f"{REF_DIR}/REF_REGION.csv", index=False)
ref_currency.to_csv(f"{REF_DIR}/REF_CURRENCY.csv", index=False)

# -----------------------------
# CUSTOMERS
# -----------------------------
print("Generating customers...")

customers = pd.DataFrame({
    "CUSTOMER_ID": [f"CUST{i}" for i in range(N_CUSTOMERS)],
    "CUSTOMER_NAME": [f"Customer_{i}" for i in range(N_CUSTOMERS)],
    "REGION_CODE": np.random.choice(ref_region["REGION_CODE"], N_CUSTOMERS),
    "STATUS": np.random.choice(["ACTIVE", "INACTIVE", "TEST"], N_CUSTOMERS, p=[0.7, 0.2, 0.1]),
    "CREATED_TS": [random_date(start_date, end_date) for _ in range(N_CUSTOMERS)]
})

customers.to_csv(f"{RAW_DIR}/SRC_CUSTOMERS.csv", index=False)

# -----------------------------
# PRODUCTS
# -----------------------------
print("Generating products...")

products = pd.DataFrame({
    "PRODUCT_ID": [f"P{i}" for i in range(N_PRODUCTS)],
    "PRODUCT_NAME": [f"Product_{i}" for i in range(N_PRODUCTS)],
    "CATEGORY": np.random.choice(["A", "B", "C", "D"], N_PRODUCTS),
    "PRICE": np.round(np.random.uniform(10, 1000, N_PRODUCTS), 2),
    "CREATED_TS": [random_date(start_date, end_date) for _ in range(N_PRODUCTS)]
})

products.to_csv(f"{RAW_DIR}/SRC_PRODUCTS.csv", index=False)

# -----------------------------
# ORDERS
# -----------------------------
print("Generating orders...")

orders = pd.DataFrame({
    "ORDER_ID": [f"O{i}" for i in range(N_ORDERS)],
    "CUSTOMER_ID": np.random.choice(customers["CUSTOMER_ID"], N_ORDERS),
    "ORDER_DATE": [random_date(start_date, end_date) for _ in range(N_ORDERS)],
    "STATUS": np.random.choice(["ACTIVE", "CANCELLED", "RETURNED"], N_ORDERS),
    "CURRENCY_CODE": np.random.choice(ref_currency["CURRENCY_CODE"], N_ORDERS),
    "CREATED_TS": [random_date(start_date, end_date) for _ in range(N_ORDERS)]
})

orders.to_csv(f"{RAW_DIR}/SRC_ORDERS.csv", index=False)

# -----------------------------
# ORDER LINES
# -----------------------------
print("Generating order lines...")

lines = pd.DataFrame({
    "LINE_ID": [f"L{i}" for i in range(N_LINES)],
    "ORDER_ID": np.random.choice(orders["ORDER_ID"], N_LINES),
    "PRODUCT_ID": np.random.choice(products["PRODUCT_ID"], N_LINES),
    "QTY": np.random.randint(1, 20, N_LINES),
})

lines["LINE_AMOUNT"] = np.round(
    lines["QTY"] * np.random.uniform(10, 1000, N_LINES), 2
)

lines["CREATED_TS"] = [random_date(start_date, end_date) for _ in range(N_LINES)]

lines.to_csv(f"{RAW_DIR}/SRC_ORDER_LINES.csv", index=False)

# -----------------------------
# PAYMENTS
# -----------------------------
print("Generating payments...")

payments = pd.DataFrame({
    "PAYMENT_ID": [f"PAY{i}" for i in range(N_PAYMENTS)],
    "ORDER_ID": np.random.choice(orders["ORDER_ID"], N_PAYMENTS),
    "AMOUNT": np.round(np.random.uniform(50, 5000, N_PAYMENTS), 2),
    "PAYMENT_STATUS": np.random.choice(["PAID", "FAILED", "PENDING"], N_PAYMENTS),
    "CREATED_TS": [random_date(start_date, end_date) for _ in range(N_PAYMENTS)]
})

payments.to_csv(f"{RAW_DIR}/SRC_PAYMENTS.csv", index=False)

print("\n✅ ALL FILES GENERATED SUCCESSFULLY")