import sys
from pathlib import Path
from dotenv import load_dotenv
import os
import json

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))



from core.scenarios.sql_mapping_builder import build_sql_mapping
from core.snowflake.target_metadata_resolver import resolve_target_metadata
from core.snowflake.target_validation import validate_scenario


# paths
MAPPING_PATH = PathMAPPING_PATH = Path("data/mapping_document/New_Dummy_mapping_doc_v1.xlsx")
SCENARIO_ROOT = Path("data/scenarios/mapping_v1")

TARGET_DATABASE = "AI_TEST"
TARGET_SCHEMA = "TARGET"
TARGET_TABLE = "TARGET_ORDERS_FACT"


def load_all_scenarios():
    scenarios = []

    # recursively search for JSON files
    for file in SCENARIO_ROOT.rglob("*.json"):
        if file.name == "scenario_summary.json":
            continue

        with open(file) as f:
            scenarios.append(json.load(f))

    return scenarios


def test_all_scenarios():

    # build mapping
    mapping = build_sql_mapping(str(MAPPING_PATH))

    # resolve metadata
    target_meta = resolve_target_metadata(
        database=TARGET_DATABASE,
        schema=TARGET_SCHEMA,
        table=TARGET_TABLE,
        mapping=mapping,
    )

    scenarios = load_all_scenarios()

    assert len(scenarios) > 0, "No scenarios found!"

    failures = []
    results = []  # collect every validation result for the summary

    for scenario in scenarios:

        result = validate_scenario(
        scenario=scenario,
        target_meta=target_meta
        )

        print("SCENARIO:", scenario.get("operation"))
        print("RESULT:", result)

        results.append(result)

        if result["status"] == "ERROR":
            failures.append(result)

    assert len(failures) == 0, f"{len(failures)} scenarios returned ERROR"

    pass_count = 0
    fail_count = 0
    skip_count = 0

    for r in results:
        if r["status"] == "PASS":
            pass_count += 1
        elif r["status"] == "FAIL":
            fail_count += 1
        elif r["status"] == "SKIPPED":
            skip_count += 1

    print("\n====== SCENARIO SUMMARY ======")
    print("PASS:", pass_count)
    print("FAIL:", fail_count)
    print("SKIP:", skip_count)
    print("==============================")