import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

# -------------------------------------------------
# PATH SETUP
# -------------------------------------------------

PROJECT_ROOT = Path("/Users/somyak/projects/My-AI-project/lyra-agentic-ai-framework")

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
REF_DIR = RAW_DIR / "reference_tables"

RAW_DIR.mkdir(parents=True, exist_ok=True)
REF_DIR.mkdir(parents=True, exist_ok=True)
# -----------------------------------

# CONFIG (FINAL)

# -----------------------------------

N_TRADES = 1_000_000
N_POSITIONS = 2_000_000
N_COUNTERPARTY = 50_000
N_INSTRUMENTS = 50_000
N_COUNTRIES = 50_000

np.random.seed(42)

# -----------------------------------

# HELPERS

# -----------------------------------

def random_dates(n):
    start = np.datetime64("2020-01-01")
    end = np.datetime64("2026-03-22")

    days = (end - start).astype("timedelta64[D]").astype(int)

    return start + np.random.randint(0, days, n).astype("timedelta64[D]")

def timestamps(n):
    base_dates = random_dates(n)
    random_seconds = np.random.randint(0, 86400, n)
    return base_dates + random_seconds.astype("timedelta64[s]")

# -----------------------------------

# KEYS

# -----------------------------------

trade_ids = np.array([f"TRD{str(i).zfill(8)}" for i in range(N_TRADES)])
instrument_ids = np.array([f"INS{str(i).zfill(6)}" for i in range(N_INSTRUMENTS)])
counterparty_ids = np.array([f"CP{str(i).zfill(6)}" for i in range(N_COUNTERPARTY)])
country_ids = np.array([f"C{str(i).zfill(5)}" for i in range(N_COUNTRIES)])

# -----------------------------------

# REF_COUNTRY (50K)

# -----------------------------------

df_country = pd.DataFrame({
"COUNTRY_CD": country_ids,
"COUNTRY_NAME": [f"Country_{i}" for i in country_ids],
"REGION": np.random.choice(["NA", "EMEA", "APAC"], N_COUNTRIES),
"IS_ACTIVE": "Y"
})

df_country.to_csv(REF_DIR / "REF_COUNTRY.csv", index=False)

# -----------------------------------

# REF_INSTRUMENT (50K)

# -----------------------------------

df_instr = pd.DataFrame({
"INSTRUMENT_CD": instrument_ids,
"INSTRUMENT_DESC": [f"Instrument {i}" for i in instrument_ids],
"INSTRUMENT_TYPE": np.random.choice(["EQUITY", "BOND", "FX"], N_INSTRUMENTS),
"IS_ACTIVE": "Y"
})

df_instr.to_csv(REF_DIR / "REF_INSTRUMENT.csv", index=False)

# -----------------------------------

# SRC_COUNTERPARTY (50K)

# -----------------------------------

df_cp = pd.DataFrame({
"CounterpartyId": counterparty_ids,
"CounterpartyType": np.random.choice(["BANK", "FUND", "CORP"], N_COUNTERPARTY),
"Country_CD": np.random.choice(country_ids, N_COUNTERPARTY),
"RiskRating": np.random.choice(["LOW", "MEDIUM", "HIGH"], N_COUNTERPARTY),
"Status": "ACTIVE",
"CREATED_TS": timestamps(N_COUNTERPARTY)
})

df_cp.to_csv(RAW_DIR / "SRC_COUNTERPARTY.csv", index=False)

# -----------------------------------

# SRC_TRADES (1M)

# -----------------------------------

df_trades = pd.DataFrame({
"TradeId": trade_ids,
"TradeDate": random_dates(N_TRADES),
"InstrumentId": np.random.choice(instrument_ids, N_TRADES),
"InstrumentType": np.random.choice(["EQUITY", "BOND", "FX"], N_TRADES),
"BuySell": np.random.choice(["BUY", "SELL"], N_TRADES),
"Quantity": np.random.randint(10, 10000, N_TRADES),
"Price": np.round(np.random.uniform(10, 500, N_TRADES), 2),
"CurrencyCode": np.random.choice(["USD", "INR", "EUR", "GBP"], N_TRADES),
"CounterpartyId": np.random.choice(counterparty_ids, N_TRADES),
"TradeStatus": np.random.choice(["NEW", "AMEND", "ACTIVE", "CANCEL"], N_TRADES),
"TraderId": np.random.randint(1, 10000, N_TRADES),
"CREATED_TS": timestamps(N_TRADES)
})

df_trades.to_csv(RAW_DIR / "SRC_TRADES.csv", index=False)

# -----------------------------------

# SRC_POSITIONS (2M, MANY PER TRADE)

# -----------------------------------

df_pos = pd.DataFrame({
"PositionId": [f"POS{str(i).zfill(9)}" for i in range(N_POSITIONS)],
"TradeId": np.random.choice(trade_ids, N_POSITIONS),
"AsOfDate": random_dates(N_POSITIONS),
"Quantity": np.random.randint(10, 10000, N_POSITIONS),
"MarketValue": np.round(np.random.uniform(1000, 500000, N_POSITIONS), 2),
"PnL": np.round(np.random.uniform(-50000, 50000, N_POSITIONS), 2),
"ValuationMethod": np.random.choice(["MTM", "MODEL"], N_POSITIONS),
"Price": np.round(np.random.uniform(10, 500, N_POSITIONS), 2),
"CREATED_TS": timestamps(N_POSITIONS)
})

df_pos.to_csv(RAW_DIR / "SRC_POSITIONS.csv", index=False)

# -----------------------------------

# SUMMARY

# -----------------------------------

print("\n📊 FINAL DATA GENERATED:")
print("SRC_TRADES:", len(df_trades))
print("SRC_POSITIONS:", len(df_pos))
print("SRC_COUNTERPARTY:", len(df_cp))
print("REF_INSTRUMENT:", len(df_instr))
print("REF_COUNTRY:", len(df_country))
