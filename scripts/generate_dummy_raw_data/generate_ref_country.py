import pandas as pd
import random
import uuid
from faker import Faker
random.seed(42)

NUM_REF_COUNTRY= 100

COUNTRY_CD= [
            "IN", "US", "GB", "DE", "FR",
            "JP", "CN", "SG", "AU", "CA"
        ]
COUNTRY_NAME=[
            "India", "United States", "United Kingdom", "Germany", "France",
            "Japan", "China", "Singapore", "Australia", "Canada"
        ]
REGION= [
            "APAC", "NA", "EU", "EU", "EU",
            "APAC", "APAC", "APAC", "APAC", "NA"
        ]
IS_ACTIVE = [True]

rows = []

for i in range(NUM_REF_COUNTRY):
    rows.append({
        "COUNTRY_CD": f"C_{i:06d}",
        "COUNTRY_NAME": random.choice(COUNTRY_NAME),
        "REGION": random.choice(REGION),
        "IS_ACTIVE": True
    })
    

df = pd.DataFrame(rows)
file_path = "/Users/somyak/projects/llm_engineering/keyrus_agentic_testing_framework/data_profiler_tool/data/raw/reference_tables/REF_COUNTRY.csv"
df.to_csv(file_path, index=False)

print(f"The file path is {file_path}")

print("The data is successfully saved in csv file")

print("REF_COUNTRY generated:", len(df))


