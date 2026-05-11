import pandas as pd
import random
import uuid
from faker import Faker
random.seed(42)

NUM_COUNTERPARTIES = 100_000

countries = ["US", "UK", "IN", "SG", "DE", "FR", "JP"]
risk_ratings = ["LOW", "MEDIUM", "HIGH"]
statuses = ["ACTIVE", "INACTIVE"]

rows = []

for i in range(NUM_COUNTERPARTIES):
    rows.append({
        "CounterpartyId": f"CP_{i:06d}",
        "CounterpartyType": random.choice(["BANK", "FUND", "BROKER"]),
        "Country_CD": random.choice(countries),
        "RiskRating": random.choices(
            risk_ratings, weights=[0.6, 0.25, 0.15]
        )[0],
        "Status": random.choices(
            statuses, weights=[0.9, 0.1]
        )[0],
    })

df = pd.DataFrame(rows)
file_path = "/Users/somyak/projects/llm_engineering/keyrus_agentic_testing_framework/data_profiler_tool/data/raw/SRC_COUNTERPARTY.csv"
df.to_csv(file_path, index=False)

print(f"The file path is {file_path}")

print("The data is successfully saved in csv file")

print("SRC_COUNTERPARTY generated:", len(df))
