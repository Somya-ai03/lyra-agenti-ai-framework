import pandas as pd
import random
from faker import Faker

fake = Faker()

# Generate 1M rows of dummy profiling data
rows = []
movements = ["CALO", "FCOP", "SALE", "FUTR", "ADJM", "MISC"]
currencies = ["USD", "INR", "GBP", "EUR"]
instrument_types = ["E", "F", "D", "B"]
buysell = ["BUY", "SELL"]
descriptions = [
    "CASH TRANSFER TO BROKER",
    "COMMISSION ON EXERCISE PAID",
    "DERIVATIVE SALE EXECUTED",
    "FUTURE CONTRACT INITIATED",
    "ADJUSTMENT ENTRY",
    "MISCELLANEOUS TRANSACTION"
]
regions = ["NA", "EMEA", "APAC", "LATAM"]
policy_types = ["TERM", "ULIP", "WHOLE", "ENDW"]

for _ in range(1000000):
    rows.append({
        "POLICY_ID": f"POL{fake.random_int(100000, 999999)}",
        "Movement": random.choice(movements),
        "CurrencyCode": random.choice(currencies),
        "InstrumentType": random.choice(instrument_types),
        "BuySell": random.choice(buysell),
        "Description": random.choice(descriptions),
        "PremiumAmount": random.randint(1000, 20000),
        "Region": random.choice(regions),
        "PolicyType": random.choice(policy_types)
    })

df = pd.DataFrame(rows)

file_path = "/Users/somyak/projects/llm_engineering/keyrus_agentic_testing_framework/dummy_data_profiler_1000000_rows.csv"
df.to_csv(file_path, index=False)

print(f"The file path is {file_path}")

print("The data is successfully saved in csv file")


