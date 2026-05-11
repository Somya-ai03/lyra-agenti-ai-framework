#!/usr/bin/env python3
import sys
from pathlib import Path
from dotenv import load_dotenv
import os
import json
import pandas as pd
from datetime import datetime
import pytest   # 🔥 NEW

load_dotenv()

print("SNOWFLAKE_USER:", os.getenv("SNOWFLAKE_USER"))

# Ensure imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.scenarios.sql_mapping_builder import build_sql_mapping
from core.profiling.profiler_engine import (
    ensure_recordid,
    detect_column_types,
    detect_column_roles,
    generate_pattern_buckets,
    select_coverage_rows,
    compute_coverage_metrics,
    detect_variance_patterns,
    attach_variance_column
)
from core.snowflake.target_validation import validate_scenario, execute_scenario, snowflake_connection
from core.scenarios.target_scenarios_builder import build_target_scenarios
from core.snowflake.target_metadata_resolver import resolve_target_metadata
from core.snowflake.load_raw_to_snowflake import sync_all_tables
from core.scenarios.ai_scenario_manager import (
    analyze_changes,
    save_mapping_snapshot,
    load_mapping_snapshot,
    get_mapping_changes,
)

# -------------------------------------------------
# PATHS
# -------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

PROFILED_DATA_DIR = DATA_DIR / "profiled"
RAW_DATA_DIR = DATA_DIR / "raw"
REFERENCE_DATA_DIR = DATA_DIR / "raw" / "reference_tables"
MAPPING_DIR = DATA_DIR / "mapping_document"
SCENARIOS_DIR = DATA_DIR / "scenarios"
OUTPUT_DIR = DATA_DIR / "output"

MAPPING_PATH = os.environ.get(
    "MAPPING_PATH",
    str(MAPPING_DIR / "New_Dummy_mapping_doc_v1.xlsx")
)

MAPPING_VERSION = "v2" if "v2" in MAPPING_PATH.lower() else "v1"

TARGET_DATABASE = os.environ.get("SNOWFLAKE_DATABASE", "AI_TEST")
TARGET_SCHEMA = os.environ.get("SNOWFLAKE_SCHEMA", "TARGET")
TARGET_TABLE = "TARGET_ORDERS_FACT"

for d in [PROFILED_DATA_DIR, OUTPUT_DIR, SCENARIOS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------
# 🔥 PYTEST GATE
# -------------------------------------------------
def run_pytest_checks():
    print("\n🧪 Running pytest regression suite...\n")

    result = pytest.main(["-q"])

    if result != 0:
        print("❌ Pytest failed. Stopping pipeline.")
        raise Exception("Pytest regression failed")

    print("✅ Pytest passed. Continuing pipeline...\n")


# -------------------------------------------------
# 🔥 BASELINE TRACKING
# -------------------------------------------------
BASELINE_FILE = SCENARIOS_DIR / "scenario_baseline.json"

def save_baseline(scenario_dir: Path):
    files = list(scenario_dir.rglob("*.json"))
    names = [f.stem for f in files]

    baseline = {
        "scenario_count": len(files),
        "scenario_names": sorted(names),
        "generated_at": datetime.now().isoformat()
    }

    with open(BASELINE_FILE, "w") as f:
        json.dump(baseline, f, indent=2)

    print(f"💾 Baseline saved ({len(files)} scenarios)")


def load_baseline():
    if not BASELINE_FILE.exists():
        return None
    with open(BASELINE_FILE) as f:
        return json.load(f)


def compare_with_baseline(scenario_dir: Path):

    print("\n📊 Running baseline comparison...")

    current_files = list(scenario_dir.rglob("*.json"))
    current_names = sorted([f.stem for f in current_files])

    baseline = load_baseline()

    if baseline is None:
        print("⚠️ No baseline found → saving first baseline")
        save_baseline(scenario_dir)
        return

    old_names = baseline["scenario_names"]

    missing = set(old_names) - set(current_names)
    new = set(current_names) - set(old_names)

    print(f"Previous count: {baseline['scenario_count']}")
    print(f"Current count : {len(current_names)}")

    if missing:
        print(f"❌ Missing scenarios: {list(missing)}")

    if new:
        print(f"➕ New scenarios: {list(new)}")

    if not missing and not new:
        print("✅ No regression detected")

    # strict mode
    if os.getenv("STRICT_REGRESSION", "false") == "true":
        if missing:
            raise Exception("Regression detected: scenarios missing")

    save_baseline(scenario_dir)


# -------------------------------------------------
# DQ PIPELINE
# -------------------------------------------------
def run_profiler_pipeline(table: str, df: pd.DataFrame) -> pd.DataFrame:

    print(f"\n🔬 PROFILING → {table}")


    df = ensure_recordid(df)
    # 🔥 FIX 1A — Force datetime parsing
    for col in df.columns:
        if "date" in col.lower() or "ts" in col.lower():
            try:
                df[col] = pd.to_datetime(df[col], errors="coerce")
            except:
                pass
    column_types = detect_column_types(df)
    roles = detect_column_roles(df, column_types)
    buckets = generate_pattern_buckets(df, column_types, roles)

    coverage_rows = select_coverage_rows(df, buckets, column_types)

    # ✅ detect variance
    variance = detect_variance_patterns(df, coverage_rows, column_types, buckets)

    # 🔥 attach variance column
    final_df = attach_variance_column(coverage_rows, variance)

    coverage_metrics = compute_coverage_metrics(buckets, coverage_rows, column_types)
    print("COLUMN TYPES:", column_types)

    print("RAW ROWS:", len(df))
    print("PROFILED ROWS:", len(coverage_rows))
    print("COVERAGE:", coverage_metrics)

    out_path = Path(PROFILED_DATA_DIR) / f"{table}_profiled.csv"

    # 🔥 save final_df instead of coverage_rows
    final_df.to_csv(out_path, index=False)

    print(f"💾 Saved profiled data → {out_path}")

    return final_df

# -------------------------------------------------
# LOAD SCENARIOS
# -------------------------------------------------
SKIP_FILES = {"scenario_baseline.json", "scenario_summary.json", "mapping_snapshot.json"}

files = [
    f for f in SCENARIOS_DIR.rglob("*.json")
    if f.name not in SKIP_FILES
]

def load_scenarios_from_dir(base_dir: Path):
    scenarios = []

    if not base_dir.exists():
        return scenarios

    for json_file in base_dir.rglob("*.json"):
        if json_file.name in SKIP_FILES:
            continue

        with open(json_file) as f:
            scenarios.append(json.load(f))

    return scenarios


def find_previous_version_scenarios(current_version: str, target_table: str):
    """
    Scan earlier mapping versions for existing scenarios.
    Returns (prev_version, prev_dir, prev_scenarios, prev_snapshot)
    or (None, None, [], None) if none found.
    """
    import re
    match = re.match(r'v(\d+)', current_version)
    if not match:
        return None, None, [], None
    cur_num = int(match.group(1))
    for v_num in range(cur_num - 1, 0, -1):
        prev_ver = f"v{v_num}"
        prev_dir = SCENARIOS_DIR / f"mapping_{prev_ver}" / target_table
        if prev_dir.exists():
            prev_sc = load_scenarios_from_dir(prev_dir)
            if prev_sc:
                prev_snap = load_mapping_snapshot(prev_dir)
                return prev_ver, prev_dir, prev_sc, prev_snap
    return None, None, [], None


def copy_scenarios_to_dir(src_dir: Path, dest_dir: Path):
    """Copy scenario JSON files preserving insert/ update/ structure."""
    import shutil
    dest_dir.mkdir(parents=True, exist_ok=True)
    for json_file in src_dir.rglob("*.json"):
        if json_file.name in SKIP_FILES:
            continue
        rel = json_file.relative_to(src_dir)
        dest_file = dest_dir / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(json_file, dest_file)


# -------------------------------------------------
# MAIN
# -------------------------------------------------
def main():

    print("\n☁️ Syncing Snowflake schema and loading data...")
    sync_all_tables()
    print("✅ Snowflake sync complete\n")

    print("🔍 Building SQL mapping...")
    mapping = build_sql_mapping(MAPPING_PATH)

    print("*"*100)
    print(mapping)
    print("*"*100)

    # ---------------- DQ ----------------
    for table in mapping["source_tables"]:
        raw_path = Path(RAW_DATA_DIR) / f"{table}.csv"

        if not raw_path.exists():
            ref_path = Path(REFERENCE_DATA_DIR) / f"{table}.csv"
            if ref_path.exists():
                raw_path = ref_path
            else:
                continue

        df = pd.read_csv(raw_path)
        run_profiler_pipeline(table, df)

    # ---------------- TARGET META ----------------
    target_meta = resolve_target_metadata(
        database=TARGET_DATABASE,
        schema=TARGET_SCHEMA,
        table=TARGET_TABLE,
        mapping=mapping,
    )

    # ---------------- SCENARIOS ----------------
    print("\n🔍 Loading scenarios...")

    scenario_dir = SCENARIOS_DIR / f"mapping_{MAPPING_VERSION}" / TARGET_TABLE
    scenario_dir.mkdir(parents=True, exist_ok=True)

    current_scenarios = load_scenarios_from_dir(scenario_dir)
    current_snapshot  = load_mapping_snapshot(scenario_dir)

    reused_count = 0
    new_count    = 0
    reused_from  = None

    if current_scenarios:
        # ── Same version: check for mapping changes ──────────────────────────
        changes = get_mapping_changes(mapping, current_snapshot)
        if not changes["has_changes"]:
            print(f"♻️  No mapping changes — reusing {len(current_scenarios)} existing scenarios")
            reused_count = len(current_scenarios)
        else:
            print(f"⚡ Mapping changed — {len(current_scenarios)} existing + generating delta")
            reused_count = len(current_scenarios)
            # delta generation handled later; track new_count after build
        existing_scenarios = current_scenarios

    else:
        # ── No current-version scenarios — look for previous version ─────────
        prev_ver, prev_dir, prev_sc, prev_snap = find_previous_version_scenarios(
            MAPPING_VERSION, TARGET_TABLE
        )

        if prev_sc:
            changes = get_mapping_changes(mapping, prev_snap)

            if not changes["has_changes"]:
                # Carry forward previous version scenarios without rebuilding
                print(f"📦 Copying {len(prev_sc)} scenarios from {prev_ver} → {MAPPING_VERSION}…")
                copy_scenarios_to_dir(prev_dir, scenario_dir)
                save_mapping_snapshot(mapping, scenario_dir, scenario_count=len(prev_sc))
                existing_scenarios = load_scenarios_from_dir(scenario_dir)
                reused_count = len(existing_scenarios)
                reused_from  = prev_ver
                print(f"♻️  Reused {reused_count} scenarios from {prev_ver} — no new functionality")
            else:
                new_cols      = changes.get("new_columns", [])
                new_joins     = changes.get("new_joins", [])
                new_filters   = changes.get("new_filters", [])
                changed_rules = changes.get("changed_rules", [])
                print(
                    f"🔁 Carrying forward {len(prev_sc)} scenarios from {prev_ver}  |  "
                    f"Delta → new columns: {len(new_cols)}, changed rules: {len(changed_rules)}, "
                    f"new joins: {len(new_joins)}, new filters: {len(new_filters)}"
                )
                if changed_rules:
                    print(f"   Changed transformation rules: {changed_rules}")
                if new_filters:
                    print(f"   New filter conditions: {new_filters}")
                copy_scenarios_to_dir(prev_dir, scenario_dir)
                reused_count = len(prev_sc)
                reused_from  = prev_ver
                # delta build happens below — current_scenarios stays empty so the build runs
                existing_scenarios = []
        else:
            print("🆕 No prior scenarios found — first run, generating from scratch")
            existing_scenarios = []

    print(
        f"\n📊 Scenario counts → "
        f"Reused: {reused_count} "
        f"{'(from ' + reused_from + ')' if reused_from else ''} | "
        f"New: (pending build) | "
        f"Total so far: {reused_count}"
    )

    #🔥 STEP 1: Ensure baseline exists BEFORE pytest
    if not BASELINE_FILE.exists():
       print("⚠️ Baseline not found → creating baseline before tests")
       save_baseline(scenario_dir)

    # 🔥 STEP 2: Run pytest
    if os.getenv("RUN_TESTS", "true") == "true":
      run_pytest_checks()

    # 🔥 STEP 3: Compare baseline AFTER tests
      compare_with_baseline(scenario_dir)

    # ---------------- VALIDATION ----------------
    print("\n🧪 Executing scenarios...")

    validation_scenarios = load_scenarios_from_dir(scenario_dir)

    results = []

    conn = snowflake_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
    TRUNCATE TABLE {TARGET_DATABASE}.{TARGET_SCHEMA}.{TARGET_TABLE}
    """)

    conn.commit()
    cursor.close()
    conn.close()

    for scenario in validation_scenarios:
        try:
            execute_scenario(scenario, target_meta)
            res = validate_scenario(scenario=scenario, target_meta=target_meta)
            status = res.get("status", "FAIL")
        except Exception:
            status = "FAIL"

        results.append({
            "operation": scenario.get("operation"),
            "status": status
        })

    summary_df = pd.DataFrame(results)

    print("\n🎯 FINAL RESULT")
    print(summary_df["status"].value_counts())


# -------------------------------------------------
if __name__ == "__main__":
    main()