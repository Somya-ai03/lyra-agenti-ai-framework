import pandas as pd
import random
from datetime import datetime

random.seed(42)

TRADES_FILE = "/Users/somyak/projects/llm_engineering/keyrus_agentic_testing_framework/data_profiler_tool/data/raw/SRC_TRADES.csv"
AS_OF_DATE = datetime(2024, 12, 31).date()

df_trades = pd.read_csv(TRADES_FILE)

rows = []

for _, trade in df_trades.iterrows():

    # Not all trades have positions (INNER vs LEFT join realism)
    if random.random() < 0.85:
        qty = trade["Quantity"]
        price = trade["Price"]

        pnl = round(random.uniform(-0.3, 0.3) * qty * price, 2)

        rows.append({
            "PositionId": f"POS_{trade.TradeId}",
            "TradeId": trade["TradeId"],
            "AsOfDate": AS_OF_DATE,
            "NetQuantity": qty,
            "MarketValue": round(qty * price, 2),
            "PnL": pnl,
            "ValuationMethod": random.choice(["MTM", "MODEL"]),
        })

df_pos = pd.DataFrame(rows)

filePath = "/Users/somyak/projects/llm_engineering/keyrus_agentic_testing_framework/data_profiler_tool/data/raw/SRC_POSITIONS.csv"
print(f"The file path is {filePath}")   



df_pos.to_csv(filePath, index=False)

print("The data is successfully saved in csv file")
print("SRC_POSITIONS generated:", len(df_pos))
