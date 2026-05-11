import pandas as pd
import random
from datetime import datetime, timedelta
from faker import Faker

random.seed(42)

NUM_TRADES = 5_00_000
START_DATE = datetime(2022, 1, 1)

instrument_types = ["FUT", "OPT", "EQ"]
buy_sell = ["BUY", "SELL"]
trade_status = ["NEW", "AMEND", "CANCEL"]
currencies = ["USD", "INR", "EUR", "GBP"]

rows = []

for i in range(NUM_TRADES):
    trade_date = START_DATE + timedelta(days=random.randint(0, 900))

    qty = random.choice([
        random.randint(1, 10_000),
        random.randint(100_000, 2_000_000)  # large qty variance driver
    ])

    rows.append({
        "TradeId": f"T{i:08d}",
        "TradeDate": trade_date.date(),
        "InstrumentId": f"INS_{random.randint(1, 50_000):06d}",
        "InstrumentType": random.choice(instrument_types),
        "BuySell": random.choice(buy_sell),
        "Quantity": qty,
        "Price": round(random.uniform(10, 5000), 2),
        "CurrencyCode": random.choice(currencies),
        "CounterpartyId": f"CP_{random.randint(0, 99_999):06d}",
        "TradeStatus": random.choices(
            trade_status, weights=[0.6, 0.3, 0.1]
        )[0],
        "TraderId": f"TRD_{random.randint(1, 500):04d}",
    })




df = pd.DataFrame(rows)
file_path = "/Users/somyak/projects/llm_engineering/keyrus_agentic_testing_framework/data_profiler_tool/data/raw/SRC_TRADES.csv"
df.to_csv(file_path, index=False)

print(f"The file path is {file_path}")

print("The data is successfully saved in csv file")

print("SRC_TRADES generated:", len(df))
