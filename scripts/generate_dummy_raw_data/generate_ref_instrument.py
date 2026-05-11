import pandas as pd
import random
import uuid
from faker import Faker
random.seed(42)

NUM_REF_INSTRUMENT= 100

INSTRUMENT_CD = [
            "INS_032227", "INS_045891", "INS_067342", "INS_078901",
            "INS_089234", "INS_091122", "INS_102334", "INS_118899",
            "INS_129001", "INS_145667"
        ]
INSTRUMENT_DESC= [
            "NIFTY FUT", "BANKNIFTY FUT", "S&P 500 FUT", "NASDAQ FUT",
            "DAX FUT", "FTSE FUT", "NIKKEI FUT", "HANGSENG FUT",
            "ASX FUT", "TSX FUT"
        ]
INSTRUMENT_TYPE= [
            "FUT", "FUT", "FUT", "FUT", "FUT",
            "FUT", "FUT", "FUT", "FUT", "FUT"
        ]
IS_ACTIVE = [True]

rows = []

for i in range(NUM_REF_INSTRUMENT):
    rows.append({
        "INSTRUMENT_CD": f"INS_{i:06d}",
        "INSTRUMENT_DESC": random.choice(INSTRUMENT_DESC),
        "INSTRUMENT_TYPE": random.choice(INSTRUMENT_TYPE),
        "IS_ACTIVE": True
    })
    

df = pd.DataFrame(rows)
file_path = "/Users/somyak/projects/llm_engineering/keyrus_agentic_testing_framework/data_profiler_tool/data/raw/reference_tables/REF_INSTRUMENT.csv"
df.to_csv(file_path, index=False)

print(f"The file path is {file_path}")

print("The data is successfully saved in csv file")

print("REF_INSTRUMENT generated:", len(df))







       
    
