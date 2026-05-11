import os
import json
import time
from datetime import datetime
import streamlit as st
import pandas as pd
from pathlib import Path

import os
from dotenv import load_dotenv

load_dotenv()  



# -------------------------------------------------
# ROOT PATH (portable)
# -------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"                 # <- add this asset directory path
PROFILED_DIR = DATA_DIR / "profiled"
PROFILED_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)  # ensure assets folder exists
(DATA_DIR / "raw" / "reference_tables").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "scenarios").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "output").mkdir(parents=True, exist_ok=True)


# -------------------------------------------------
# IMPORT CORE
# -------------------------------------------------
from core.scenarios.sql_mapping_builder import build_sql_mapping
from core.scenarios.target_scenarios_builder import build_target_scenarios, merge_update_scenarios
from core.scenarios.ai_scenario_manager import (
    save_mapping_snapshot,
    load_mapping_snapshot,
    get_mapping_changes,
)
from core.snowflake.target_validation import execute_query, validate_scenario, validate_scenario_debug, execute_scenario, snowflake_connection
from core.snowflake.target_metadata_resolver import resolve_target_metadata
from core.profiling.mapping_coverage import compute_mapping_coverage, compute_coverage_gap_analysis
# ✅ ADD THIS
from core.profiling.profiler_engine import (
    ensure_recordid,
    dataset_overview,
    detect_column_types,
    column_statistics,
    value_distribution,
    pattern_detection,
    detect_column_roles,
    generate_pattern_buckets,
    select_coverage_rows,
    compute_coverage_metrics,
    detect_variance_patterns,
    attach_variance_column,
    build_profiler_output,
    profiling_report,
)
from core.ai.auto_discovery import (
    discover_mapping_files,
    discover_profiled_files,
    discover_scenario_dirs,
    find_best_source_file,
    discover_all,
)
from core.ai.ai_engine import (
    ai_available,
    ai_validate_mapping,
    ai_dq_summary,
    ai_suggest_edge_cases,
    ai_root_cause_analysis,
    ai_chat,
    ai_nl_to_sql,
    ai_dq_anomalies,
    ai_mapping_suggestions,
    ai_generate_report,
    AI_STATUS_MESSAGES,
)

# -------------------------------------------------
# HELPERS
# -------------------------------------------------
def safe_display_df(df: pd.DataFrame):
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].astype(str)
    return df


def _json_safe(obj):
    """
    Recursively convert non-JSON-serializable values (Timestamp, date,
    Decimal, numpy types, etc.) to strings so json.dumps never raises.
    """
    import decimal, datetime
    import numpy as np

    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (datetime.datetime, datetime.date, pd.Timestamp)):
        return str(obj)
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def save_profiled_table(table_name: str, df):
    path = PROFILED_DIR / f"{table_name}_profiled.csv"
    df.to_csv(path, index=False)
    return path


_SKIP_JSON = {"scenario_summary.json", "mapping_snapshot.json", "scenario_baseline.json", "execution_log.json"}


def save_execution_log(exec_log: dict, scenario_dir: Path):
    """Persist the execution log next to the scenarios so it survives page refreshes."""
    if not exec_log:
        return
    path = Path(scenario_dir) / "execution_log.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(_json_safe(exec_log), f, indent=2)


def load_execution_log(scenario_dir: Path) -> dict:
    """Load a previously saved execution log from the scenario directory."""
    path = Path(scenario_dir) / "execution_log.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def load_scenarios_from_dir(base_dir: Path):
    scenarios = []
    if not base_dir or not Path(base_dir).exists():
        return scenarios
    for json_file in Path(base_dir).rglob("*.json"):
        if json_file.name in _SKIP_JSON:
            continue
        with open(json_file) as f:
            scenarios.append(json.load(f))
    return scenarios


def detect_mapping_version(mapping_file) -> str:
    """Extract version from mapping filename, e.g. 'v1', 'v2', 'v3'."""
    import re
    name = str(mapping_file).lower()
    match = re.search(r'_v(\d+)', name)
    return f"v{match.group(1)}" if match else "v1"


def find_previous_version_scenarios(current_version: str, target_table: str, scenarios_base: Path):
    """
    Scan for scenarios from any earlier mapping version.
    Returns (prev_version, prev_dir, prev_scenarios, prev_snapshot)
    or (None, None, [], None) when nothing is found.
    """
    import re
    match = re.match(r'v(\d+)', current_version)
    if not match:
        return None, None, [], None
    cur_num = int(match.group(1))
    for v_num in range(cur_num - 1, 0, -1):
        prev_version = f"v{v_num}"
        prev_dir = scenarios_base / f"mapping_{prev_version}" / target_table
        if prev_dir.exists():
            prev_sc = load_scenarios_from_dir(prev_dir)
            if prev_sc:
                prev_snap = load_mapping_snapshot(prev_dir)
                return prev_version, prev_dir, prev_sc, prev_snap
    return None, None, [], None


def copy_scenarios_to_dir(src_dir: Path, dest_dir: Path):
    """
    Copy all scenario JSON files from src_dir into dest_dir,
    preserving the insert/ update/ subdirectory structure.
    Skips snapshot / summary files.
    """
    import shutil
    dest_dir.mkdir(parents=True, exist_ok=True)
    for json_file in Path(src_dir).rglob("*.json"):
        if json_file.name in _SKIP_JSON:
            continue
        rel = json_file.relative_to(src_dir)
        dest_file = dest_dir / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(json_file, dest_file)


def ai_status(category: str, step: int = 0):
    """Get contextual AI status message."""
    msgs = AI_STATUS_MESSAGES.get(category, ["Processing..."])
    return msgs[min(step, len(msgs) - 1)]


def build_session_context() -> dict:
    """Build context dict from session state for AI chat."""
    ctx = {}
    if st.session_state.get("mapping_extracted"):
        m = st.session_state.mapping_extracted
        ctx["mapping"] = {
            "source_tables": m.get("source_tables", []),
            "join_count": len(m.get("joins", [])),
            "filter_count": len(m.get("filters", [])),
            "target_column_count": len(m.get("target_columns", {})),
        }
    if st.session_state.get("profiled_tables"):
        ctx["profiled_tables"] = {
            t: {"rows": len(df), "columns": len(df.columns)}
            for t, df in st.session_state.profiled_tables.items()
        }
    if st.session_state.get("scenario_df") is not None:
        sdf = st.session_state.scenario_df
        ctx["scenarios"] = {"count": len(sdf)}
    if st.session_state.get("validation_df") is not None:
        vdf = st.session_state.validation_df
        if isinstance(vdf, pd.DataFrame) and "status" in vdf.columns:
            ctx["validation"] = {
                "total": len(vdf),
                "passed": int((vdf["status"] == "PASS").sum()),
                "failed": int((vdf["status"] == "FAIL").sum()),
            }
    cov = st.session_state.get("mapping_coverage")
    if cov:
        ctx["coverage"] = cov
    return ctx




from PIL import Image
import os

def convert_png_to_jpg(input_path, output_path, quality=85):
    img = Image.open(input_path)

    # Convert RGBA → RGB (important for PNG with transparency)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    img.save(output_path, "JPEG", quality=quality, optimize=True)


# Example usage
convert_png_to_jpg("assets/current_process.png", "assets/current_process.jpg")
convert_png_to_jpg("assets/with_ai.png", "assets/with_ai.jpg")

print("✅ Conversion complete")






# -------------------------------------------------
# STREAMLIT CONFIG
# -------------------------------------------------

st.set_page_config(
    page_title="Agentic Data Testing Platform",
    layout="wide",
    page_icon="📊"
)


# -------------------------------------------------
# CUSTOM CSS
# -------------------------------------------------
st.markdown("""
<style>
    .ai-badge {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.75em;
        font-weight: 600;
    }
    .ai-insight {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        border-left: 4px solid #667eea;
        padding: 12px 16px;
        border-radius: 0 8px 8px 0;
        margin: 8px 0;
    }
    .discovery-card {
        background: #f0f9ff;
        border: 1px solid #bae6fd;
        border-radius: 8px;
        padding: 12px;
        margin: 4px 0;
    }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------
# TITLE & AI STATUS
# -------------------------------------------------
col_title, col_ai = st.columns([4, 1])
with col_title:

    st.title("📊 Agentic Data Testing Platform")
    #st.markdown('<p style="font-size: 18px; margin-top: -10px; font-weight: 500;">Core Developer: <b style="color: #e94560;">Somya Kaushik</b> <span style="opacity: 0.7;">(QA Consultant)</span></p>', unsafe_allow_html=True)
    

# -------------------------------------------------
# SESSION STATE
# -------------------------------------------------
for key, default in {
    "mapping_extracted": None,
    "mapping_file": None,
    "source_tables": [],
    "scenario_df": None,
    "validation_df": None,
    "target_meta": None,
    "scenario_dir": None,
    "mapping_coverage": None,
    "execution_log": None,
    "profiled_tables": {},
    "static_tables": {},
    "target_tables": [],
    "last_target_table": None,
    "ai_mapping_review": None,
    "ai_dq_summaries": {},
    "ai_dq_anomalies": {},
    "ai_edge_cases": None,
    "ai_chat_history": [],
    "ai_report": None,
    "discovered_assets": None,
    # --- scenario reuse tracking ---
    "scenario_reused_count": 0,
    "scenario_new_count": 0,
    "scenario_reused_from_version": None,
}.items():
    st.session_state.setdefault(key, default)

# -------------------------------------------------
# AUTO-DISCOVERY (run once)
# -------------------------------------------------
if st.session_state.discovered_assets is None:
    st.session_state.discovered_assets = discover_all(DATA_DIR)

discovered = st.session_state.discovered_assets

# =================================================
# SIDEBAR — AI CHAT ASSISTANT (Feature 5)
# =================================================
with st.sidebar:
    st.markdown("## 🤖 AI Assistant")

    if not ai_available():
        st.info("Set `AZURE_OPENAI_API_KEY` and endpoint to enable AI chat")
    else:
        # Show discovered assets summary
        with st.expander("📁 Discovered Data Assets", expanded=False):
            n_maps = len(discovered.get("mapping_files", []))
            n_prof = len(discovered.get("profiled_files", {}))
            n_raw = len(discovered.get("raw_files", {}))
            n_sample = len(discovered.get("sample_files", {}))
            n_scen = len(discovered.get("scenario_dirs", {}))
            st.markdown(f"""
            - **{n_maps}** mapping documents
            - **{n_prof}** profiled tables
            - **{n_raw}** raw data files
            - **{n_sample}** sample files
            - **{n_scen}** scenario sets
            """)

        # Chat interface
        st.markdown("---")
        st.caption("Ask me about your data quality, mapping coverage, or test results")

        # Display chat history
        for msg in st.session_state.ai_chat_history:
            role = "🧑" if msg["role"] == "user" else "🤖"
            st.markdown(f"**{role}** {msg['content']}")

        chat_input = st.text_input("💬 Ask AI...", key="chat_input", placeholder="e.g. Which columns have worst DQ?")

        if chat_input:
            st.session_state.ai_chat_history.append({"role": "user", "content": chat_input})

            with st.spinner("🧠 Thinking..."):
                ctx = build_session_context()
                response = ai_chat(chat_input, ctx, st.session_state.ai_chat_history)

                if response:
                    if isinstance(response, str) and response.startswith("[AI Error]"):
                      st.error(response)  # 👈 shows clean UI error
                    else:
                        st.session_state.ai_chat_history.append({
                        "role": "assistant",
                        "content": response
                    })
                    st.rerun()

        if st.session_state.ai_chat_history:
            if st.button("🗑️ Clear Chat"):
                st.session_state.ai_chat_history = []
                st.rerun()
    
    if not st.session_state.ai_chat_history:
       st.caption("💡 Try asking: 'Summarize data quality issues'")

# -------------------------------------------------
# TABS
# -------------------------------------------------
tabs = st.tabs([
    "🏗️ Architecture",
    "📘 Mapping",
    "🧪 Profiling",
    "🧩 Scenarios",
    "❄️ Snowflake Validation",
    "🔬 Mapping Coverage Analysis",
    "📊 Dashboard",
    "🔎 Failed Scenarios",
])



# =================================================

# TAB 1 — ARCHITECTURE (DEMO-OPTIMIZED)

# ================================================= 

from pathlib import Path
import streamlit as st

# ✅ MUST BE FIRST LINE
st.set_page_config(layout="wide")

with tabs[0]:

    st.markdown("# 🏗️ Intelligent Data Validation Platform")

    st.markdown(
        """
        <div style="padding:14px;border-radius:12px;
        background:linear-gradient(90deg,#1f3c88,#0f2027);
        color:white;">
        Transforming manual validation into an automated, AI-powered pipeline
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("---")

    st.subheader("🧭 From Current → AI-Powered Validation")

    BASE_DIR = Path(__file__).parent
    img1 = BASE_DIR / "assets" / "current_process.jpg"
    img2 = BASE_DIR / "assets" / "with_ai.jpg"

    col1, col2 = st.columns(2)

    from PIL import Image

    img1_pil = Image.open(img1)
    img2_pil = Image.open(img2)

    col1, col2 = st.columns([1,1], gap="large")

    with col1:
        st.markdown("### 🔴 Current Validation Process")
        st.image(img1_pil, width= 1000)

    with col2:
        st.markdown("### 🟢 AI-Powered Validation Approach")
        st.image(img2_pil, width=1000)
        st.markdown("---")

    # 📊 IMPACT
    st.subheader("📊 What Changes")

    c1, c2, c3 = st.columns(3)

    c1.metric("Manual Effort", "Reduced")
    c2.metric("Automation", "High")
    c3.metric("Coverage", "End-to-End")

    st.markdown("---")

# 🧱 TECH STACK
    st.subheader("🧱 Tech Stack")

    st.markdown("""
**Streamlit** • **Python** • **Snowflake** • **Microsoft Azure (incl. Azure AI Foundry & AI Services)** 
""")

    st.markdown("---")

# ✨ FINAL MESSAGE
    st.success("🚀 Enabling faster, scalable, and intelligent data validation")









# =================================================
# TAB 2 — MAPPING (with AI Validator + Smart Discovery)
# =================================================     
with tabs[1]:
    st.header("📘 SQL Mapping Extraction")

    # ----- Auto-discovery: show available mapping files -----
    mapping_files = discovered.get("mapping_files", [])

    mapping_source = None

    if mapping_files:
        st.markdown('<div class="discovery-card">🔍 <b>Auto-discovered mapping files:</b></div>', unsafe_allow_html=True)

        file_names = [f.name for f in mapping_files]
        options = ["-- Select a discovered file --"] + file_names + ["📤 Upload new file"]

        choice = st.selectbox("Choose mapping document", options, key="mapping_choice")

        if choice == "📤 Upload new file":
            mapping_source = st.file_uploader("Upload Mapping Excel", type=["xlsx"], key="mapping_upload_new")
        elif choice != "-- Select a discovered file --":
            idx = file_names.index(choice)
            mapping_source = mapping_files[idx]
            st.success(f"✅ Using discovered file: `{choice}`")
    else:
        mapping_source = st.file_uploader("Upload Mapping Excel", type=["xlsx"], key="mapping_upload")

    # ----- Extract mapping -----
    if mapping_source is not None:
        if st.button("🔍 Extract Mapping", key="btn_extract_mapping"):
            progress = st.empty()
            progress.info(ai_status("mapping_extract", 0))

            mapping = build_sql_mapping(mapping_source)

            progress.info(ai_status("mapping_extract", 1))

            st.session_state.mapping_extracted = mapping
            st.session_state.mapping_file = mapping_source
            st.session_state.source_tables = mapping.get("source_tables", [])

            progress.info(ai_status("mapping_extract", 2))
            time.sleep(0.3)
            progress.success(ai_status("mapping_extract", 3))

            st.write("**Source Tables:**", mapping.get("source_tables", []))
            st.write(f"**Joins:** {len(mapping.get('joins', []))}")
            st.write(f"**Filters:** {len(mapping.get('filters', []))}")
            st.write(f"**Target Columns:** {len(mapping.get('target_columns', {}))}")

    # ----- AI Mapping Review (Feature 1) -----
    if st.session_state.get("mapping_extracted") and ai_available():
        st.markdown("---")
        st.subheader("🤖 AI Mapping Review")

        if st.button("🔬 Run AI Analysis", key="btn_ai_mapping"):
            with st.spinner(ai_status("ai_review", 0)):
                review = ai_validate_mapping(st.session_state.mapping_extracted)

                if isinstance(review, str) and review.startswith("[AI Error]"):
                    st.error(review)

                elif isinstance(review, dict) and "raw_response" in review:
                    st.error("⚠️ AI did not return valid JSON")
                    st.code(review["raw_response"])

                else:
                    st.session_state.ai_mapping_review = review
                
        review = st.session_state.get("ai_mapping_review")
        if review and isinstance(review, dict):
            # Confidence meter
            confidence = review.get("overall_confidence", 0)
            st.metric("Overall Confidence", f"{confidence}%")
            st.progress(confidence / 100)

            col1, col2 = st.columns(2)
            with col1:
                jr = review.get("joins_review", {})
                st.markdown(f"**Joins:** {jr.get('count', 0)} detected | Confidence: {jr.get('confidence', 'N/A')}%")
                for issue in jr.get("issues", []):
                    st.warning(f"⚠️ {issue}")

            with col2:
                cr = review.get("column_mapping_review", {})
                st.markdown(f"**Columns:** {cr.get('count', 0)} mapped | Confidence: {cr.get('confidence', 'N/A')}%")
                for tm in cr.get("type_mismatches", []):
                    st.warning(f"⚠️ {tm}")

            recs = review.get("recommendations", [])
            if recs:
                st.markdown("**💡 Recommendations:**")
                for r in recs:
                    st.info(f"→ {r}")

    # ----- AI Smart Mapping Suggestions (Feature 8) -----
    if st.session_state.get("mapping_extracted") and ai_available():
        all_available = list(discovered.get("raw_files", {}).keys()) + \
                        list(discovered.get("sample_files", {}).keys()) + \
                        list(discovered.get("profiled_files", {}).keys())
        all_available = sorted(set(all_available))

        if all_available:
            with st.expander("🧠 AI Smart Table Matching", expanded=False):
                if st.button("Match Source Tables to Data Files", key="btn_ai_match"):
                    with st.spinner("🧠 Analyzing table-to-file mappings..."):
                        suggestions = ai_mapping_suggestions(
                            st.session_state.mapping_extracted,
                            all_available,
                        )
                    if suggestions and isinstance(suggestions, dict):
                        for match in suggestions.get("table_matches", []):
                            conf = match.get("confidence", 0)
                            icon = "✅" if conf >= 80 else "⚠️" if conf >= 50 else "❌"
                            st.markdown(f"{icon} **{match['mapping_table']}** → `{match.get('best_match', '?')}` ({conf}% match)")

                        mismatches = suggestions.get("column_mismatches", [])
                        if mismatches:
                            st.markdown("**🔀 Column Name Mismatches:**")
                            for m in mismatches:
                                st.caption(f"`{m.get('mapping_column')}` ↔ `{m.get('likely_data_column')}` ({m.get('table')})")

                        for s in suggestions.get("suggestions", []):
                            st.info(f"💡 {s}")


 #---------------using to detect latest timestamp row for profiling-----------------------------------                           

import os

def should_reprofile(raw_path, profiled_path):
    """
    Returns True if raw data is newer than profiled data
    """

    if not profiled_path.exists():
        return True  # no profiled file → must profile

    raw_time = os.path.getmtime(raw_path)
    profiled_time = os.path.getmtime(profiled_path)

    return raw_time > profiled_time


# =================================================
# TAB 3 — PROFILING (with AI DQ Summary + Anomalies + Auto-Discovery)
# =================================================

with tabs[2]:

    if not st.session_state.get("mapping_extracted"):
        st.info("📘 Extract mapping first (Tab 1)")
        st.stop()

    st.header("🧪 Data Profiling")

    source_tables = st.session_state.get("source_tables", [])
    if not source_tables:
        st.warning("No source tables found in mapping")
        st.stop()

    # -------------------------------
    # Helper
    # -------------------------------
    def get_variance_count(df):
        if "variance" not in df.columns:
            return 0
        return df["variance"].astype(str).str.strip().ne("").sum()

    # -------------------------------
    # LOOP TABLES
    # -------------------------------
    for table in source_tables:

        with st.expander(f"📂 {table}", expanded=False):
           

            best = find_best_source_file(table, DATA_DIR)

            if best:
                st.markdown(
                    f'<div class="discovery-card">🔍 Using <b>{best["source_type"]}</b> file: <code>{best["path"].name}</code></div>',
                    unsafe_allow_html=True
                )
            else:
                st.warning(f"⚠️ No data file found for {table}")
                continue

            # =================================================
            # CASE 1 — PROFILED FILE EXISTS → LOAD + COVERAGE
            # =================================================
            profiled_path = best["path"]

            raw_file = find_best_source_file(table, DATA_DIR)
            raw_path = raw_file["path"] if raw_file else None

            if best["source_type"] == "profiled" and raw_path and not should_reprofile(raw_path, profiled_path):

                df = pd.read_csv(best["path"])
                df.columns = [c.strip().lower() for c in df.columns]

                st.session_state.profiled_tables[table] = df

                try:
                    column_types = detect_column_types(df)
                    roles = detect_column_roles(df, column_types)

                    buckets = generate_pattern_buckets(df, column_types, roles)

                    coverage_metrics = compute_coverage_metrics(
                        buckets,
                        df,
                        column_types
                    )

                    st.session_state[f"{table}_coverage"] = coverage_metrics

                except Exception as e:
                    st.warning(f"⚠️ Coverage computation skipped: {e}")

                st.success(f"✅ Loaded profiled data for {table}")

            # =================================================
            # CASE 2 — RAW/SAMPLE → AUTO PROFILE (FIXED)
            # =================================================
            elif best["source_type"] in ("raw", "sample"):

                if table not in st.session_state.profiled_tables or should_reprofile(raw_path, profiled_path):

                    st.info(f"⚡ Auto-profiling {table}...")

                    try:
                        df = load_from_blob(best["path"].name)
                    except Exception:
                        df = pd.read_csv(best["path"])

                    # 🔥 ADD THIS LINE
                       # df = apply_latest_batch_logic(df)

                    # STEP 1 — Ensure RecordId
                    df = ensure_recordid(df)

                    # 🔥 STEP 2 — Create profiling copy WITHOUT RecordId
                    profile_df = df[[col for col in df.columns if col.lower() != "recordid"]]

                    # STEP 3 — Profiling pipeline (use profile_df)
                    overview = dataset_overview(profile_df)
                    column_types = detect_column_types(profile_df)
                    roles = detect_column_roles(profile_df, column_types)

                    stats = column_statistics(profile_df, column_types)
                    distributions = value_distribution(profile_df, column_types)
                    patterns = pattern_detection(profile_df, column_types)

                    # STEP 4 — Buckets
                    buckets = generate_pattern_buckets(profile_df, column_types, roles)

                    # STEP 5 — Coverage rows
                    selected_rows = select_coverage_rows(profile_df, buckets, column_types)

                    # STEP 6 — Coverage metrics
                    coverage_metrics = compute_coverage_metrics(
                        buckets,
                        selected_rows,
                        column_types
                    )

                    # 🔥 STEP 7 — Reattach RecordId (IMPORTANT)
                    selected_rows = df.loc[selected_rows.index]

                    # STEP 8 — Variance explanation
                    variance_explanations = detect_variance_patterns(
                        df,
                        selected_rows,
                        column_types,
                        buckets
                    )

                    selected_rows = attach_variance_column(
                        selected_rows,
                        variance_explanations
                    )

                    # STEP 9 — Normalize + Save
                    selected_rows.columns = [c.strip().lower() for c in selected_rows.columns]

                    st.session_state.profiled_tables[table] = selected_rows
                    save_profiled_table(table, selected_rows)

                    st.session_state[f"{table}_coverage"] = coverage_metrics

                    st.success(f"✅ Profiling completed for {table}")

                else:
                    df = st.session_state.profiled_tables[table]

            # =================================================
            # DISPLAY (COMMON)
            # =================================================
            df = st.session_state.profiled_tables.get(table)

            if df is None:
                st.warning("No profiled data available")
                continue

            coverage = st.session_state.get(f"{table}_coverage", {})

            c1, c2, c3, c4 = st.columns(4)

            c1.metric("Rows", len(df))
            c2.metric("Columns", len(df.columns))
            c3.metric("Variance Rows", get_variance_count(df))

            if coverage:
                c4.metric(
                    "Coverage %",
                    coverage.get("coverage_percent", 0),
                    delta=f"{coverage.get('covered_patterns', 0)}/{coverage.get('total_patterns', 0)}"
                )
            else:
                c4.metric("Coverage %", "N/A")

            # -------------------------------
            # Coverage Details
            # -------------------------------
            if coverage:
                with st.expander("📊 Coverage Details"):
                    st.json(coverage)

            # -------------------------------
            # Data Preview
            # -------------------------------
            st.markdown("### 📈 Sampled Data")
            st.dataframe(safe_display_df(df.head(20)))

            # -------------------------------
            # Variance Breakdown
            # -------------------------------
            if "variance" in df.columns:
                with st.expander("🔍 Variance Breakdown"):
                    st.write(df["variance"].value_counts().head(10))



# =================================================
# TAB 4 — SCENARIOS (UI CLEANED + INTERACTIVE)
# =================================================

with tabs[3]:

    st.header("🧩 Scenario Builder")

    # =================================================
    # 🎯 TARGET SELECTION
    # =================================================
    st.subheader("🎯 Select Target Table")

    target_options = ["TARGET_TRADES", "TARGET_ORDERS_FACT"]

    default_index = 0
    last_target = st.session_state.get("last_target_table")
    if last_target in target_options:
        default_index = target_options.index(last_target)

    col1, col2 = st.columns([3, 1])

    with col1:
        new_target = st.selectbox(
            "Target Table",
            target_options,
            index=default_index
        )

    with col2:
        st.write("")
        st.write("")
        build_clicked = st.button("🚀 Build")

    st.session_state["last_target_table"] = new_target

    # =================================================
    # 📦 SCENARIO AVAILABILITY (CROSS-VERSION AWARE)
    # =================================================
    mapping_file = st.session_state.get("mapping_file")

    if mapping_file and new_target:

        mapping_version = detect_mapping_version(mapping_file)
        scenarios_base  = DATA_DIR / "scenarios"
        curr_dir        = scenarios_base / f"mapping_{mapping_version}" / new_target

        curr_sc = load_scenarios_from_dir(curr_dir) if curr_dir.exists() else []

        st.markdown("### 📦 Scenario Availability")

        just_created = st.session_state.get("just_created_scenarios", False)

        if curr_sc:
            if just_created:
                st.success(
                f"🆕 **{len(curr_sc)}** scenarios successfully created for `{mapping_version}` → **{new_target}**"
            )
                st.session_state.just_created_scenarios = False
            else:
                st.success(
                f"✅ **{len(curr_sc)}** scenarios already exist for `{mapping_version}` → **{new_target}**")
            
           
        else:
            prev_ver, _, prev_sc, _ = find_previous_version_scenarios(
                mapping_version, new_target, scenarios_base
            )
            if prev_sc:
                st.info(
                    f"📦 No `{mapping_version}` scenarios yet — "
                    f"**{len(prev_sc)}** reusable scenarios found from **{prev_ver}**. "
                    f"Click **Build** to carry them forward + generate only the delta."
                )
            else:
                st.info(f"No existing scenarios found for **{new_target}** — first run will generate from scratch.")

    # =================================================
    # 🚀 BUILD FLOW — smart cross-version reuse
    # =================================================
    if build_clicked:

        if not st.session_state.get("mapping_file"):
            st.error("Upload mapping first (Tab 1)")
            st.stop()

        if new_target not in st.session_state.target_tables:
            st.session_state.target_tables.append(new_target)

        if st.session_state.get("target_meta") and st.session_state.target_meta.get("table") == new_target:
            build_meta = st.session_state.target_meta
        else:
            build_meta = {"table": new_target, "business_keys": []}

        progress = st.empty()
        progress.info("⚙️ Preparing scenarios...")

        mapping_file    = st.session_state.mapping_file
        mapping_version = detect_mapping_version(mapping_file)
        scenarios_base  = DATA_DIR / "scenarios"
        base_scenario_dir = scenarios_base / f"mapping_{mapping_version}" / new_target
        base_scenario_dir.mkdir(parents=True, exist_ok=True)

        mapping     = build_sql_mapping(mapping_file)
        current_sc  = load_scenarios_from_dir(base_scenario_dir)
        curr_snap   = load_mapping_snapshot(base_scenario_dir)

        st.subheader("🧠 Scenario Engine Mode")

        # ----------------------------------------------------------
        # CASE 1 — same version, mapping unchanged → pure reuse
        # ----------------------------------------------------------
        if current_sc:
            changes = get_mapping_changes(mapping, curr_snap)

            if not changes["has_changes"]:
                progress.empty()

                rows = [{
                    "scenario_id": s.get("scenario_id", ""),
                    "operation":   s.get("operation", ""),
                    "target_table": new_target,
                    "source": "reused",
                } for s in current_sc]

                st.session_state.scenario_df              = pd.DataFrame(rows)
                st.session_state.scenario_dir             = base_scenario_dir
                # load saved log so coverage tab works even on pure reuse
                st.session_state.execution_log            = load_execution_log(base_scenario_dir)
                st.session_state.scenario_reused_count    = len(current_sc)
                st.session_state.scenario_new_count       = 0
                st.session_state.scenario_reused_from_version = mapping_version

                st.success(f"♻️ Mapping unchanged — reusing all existing `{mapping_version}` scenarios")

                st.markdown("### 📊 Scenario Summary")
                col1, col2, col3 = st.columns(3)
                col1.metric(f"♻️ Reused ({mapping_version})", len(current_sc))
                col2.metric("🆕 New (delta)", 0)
                col3.metric("📦 Total", len(current_sc))

            # ----------------------------------------------------------
            # CASE 2 — same version, mapping changed → incremental delta
            # ----------------------------------------------------------
            else:
                new_cols      = changes.get("new_columns", [])
                new_joins     = changes.get("new_joins", [])
                new_filters   = changes.get("new_filters", [])
                changed_rules = changes.get("changed_rules", [])

                st.warning(
                    f"⚡ Mapping changed in `{mapping_version}` — incremental update  \n"
                    f"New columns: **{len(new_cols)}** | Changed rules: **{len(changed_rules)}** | "
                    f"New joins: **{len(new_joins)}** | New filters: **{len(new_filters)}**"
                )

                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                build_output_dir = base_scenario_dir / f"delta_{ts}"
                build_output_dir.mkdir(parents=True, exist_ok=True)

                try:
                    MAX_NEW_SCENARIOS = 5
                   
                    result_df, _, exec_log = build_target_scenarios(
                    mapping_path=mapping_file,
                    target_meta=build_meta,
                     output_dir=build_output_dir,
                    )

                    # 🔥 LIMIT FIRST
                    if result_df is not None and not result_df.empty:
                        result_df = result_df.head(MAX_NEW_SCENARIOS)

                        pk_cols = build_meta.get("business_keys", [])

                        updated_sc, new_sc = merge_update_scenarios(current_sc, result_df, pk_cols)

                    

                except (ValueError, FileNotFoundError) as e:
                    progress.empty()
                    st.error(f"Scenario generation failed: {e}")
                    st.stop()

                reused_count = len(current_sc)
                new_count    = len(result_df) if result_df is not None else 0
                total_after  = len(load_scenarios_from_dir(base_scenario_dir))
                save_mapping_snapshot(mapping, base_scenario_dir, scenario_count=total_after)

                progress.success("✅ Incremental scenario generation complete")

                all_rows = (
                            [{"scenario_id": s.get("scenario_id",""), "operation": s.get("operation",""),
                            "target_table": new_target, "source": "updated"} for s in updated_sc]
                            + [{"scenario_id": s.get("scenario_id",""), "operation": s.get("operation",""),
                         "target_table": new_target, "source": "new"} for s in new_sc]
                        )
                save_execution_log(exec_log, base_scenario_dir)
                st.session_state.scenario_df              = pd.DataFrame(all_rows)
                st.session_state.scenario_dir             = base_scenario_dir
                st.session_state.execution_log            = exec_log
                st.session_state.scenario_reused_count    = reused_count
                st.session_state.scenario_new_count       = new_count
                st.session_state.scenario_reused_from_version = mapping_version
                st.session_state.discovered_assets        = discover_all(DATA_DIR)

                st.markdown("### 📊 Scenario Summary")
                col1, col2, col3 = st.columns(3)
                col1.metric(f"♻️ Reused ({mapping_version})", reused_count)
                col2.metric("🆕 New (delta)", new_count)
                col3.metric("📦 Total", reused_count + new_count)
                st.success(f"Total coverage: **{reused_count + new_count}** scenarios")

                if result_df is not None and not result_df.empty:
                    st.markdown("### 🆕 New Delta Scenarios")
                    st.dataframe(result_df.head(20), use_container_width=True)

        # ----------------------------------------------------------
        # CASE 3 — no current-version scenarios, check prev versions
        # ----------------------------------------------------------
        else:
            prev_ver, prev_dir, prev_sc, prev_snap = find_previous_version_scenarios(
                mapping_version, new_target, scenarios_base
            )

            if prev_sc:
                reused_count = len(prev_sc)
                changes      = get_mapping_changes(mapping, prev_snap)

                # ---- 3a: no delta → just carry forward ----
                if not changes["has_changes"]:
                    progress.info(f"📦 Copying {reused_count} scenarios from {prev_ver} → {mapping_version}…")
                    copy_scenarios_to_dir(prev_dir, base_scenario_dir)
                    save_mapping_snapshot(mapping, base_scenario_dir, scenario_count=reused_count)

                    all_sc = load_scenarios_from_dir(base_scenario_dir)
                    rows = [{
                        "scenario_id": s.get("scenario_id",""),
                        "operation":   s.get("operation",""),
                        "target_table": new_target,
                        "source": f"reused_from_{prev_ver}",
                    } for s in all_sc]

                    st.session_state.scenario_df              = pd.DataFrame(rows)
                    st.session_state.scenario_dir             = base_scenario_dir
                    # load from whichever dir has a saved log (current or prev version)
                    st.session_state.execution_log            = (
                        load_execution_log(base_scenario_dir) or
                        load_execution_log(prev_dir)
                    )
                    st.session_state.scenario_reused_count    = reused_count
                    st.session_state.scenario_new_count       = 0
                    st.session_state.scenario_reused_from_version = prev_ver

                    progress.success(f"✅ Carried forward {reused_count} scenarios from {prev_ver} — no new functionality detected")

                    st.markdown("### 📊 Scenario Summary")
                    col1, col2, col3 = st.columns(3)
                    col1.metric(f"♻️ Reused (from {prev_ver})", reused_count)
                    col2.metric("🆕 New (delta)", 0)
                    col3.metric("📦 Total", reused_count)

                # ---- 3b: has delta → carry forward + build delta only ----
                else:
                    new_cols    = changes.get("new_columns", [])
                    new_joins   = changes.get("new_joins", [])
                    new_filters = changes.get("new_filters", [])

                    changed_rules = changes.get("changed_rules", [])
                    st.info(
                        f"🔁 Carrying forward **{reused_count}** scenarios from **{prev_ver}**  \n"
                        f"➕ New functionality — New columns: **{len(new_cols)}** | "
                        f"Changed rules: **{len(changed_rules)}** | "
                        f"New joins: **{len(new_joins)}** | New filters: **{len(new_filters)}**"
                    )

                    progress.info(f"📦 Copying {reused_count} scenarios from {prev_ver}…")
                    copy_scenarios_to_dir(prev_dir, base_scenario_dir)

                    progress.info("⚙️ Generating new scenarios for delta functionality…")

                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    delta_output_dir = base_scenario_dir / f"delta_from_{prev_ver}_{ts}"
                    delta_output_dir.mkdir(parents=True, exist_ok=True)

                    try:
                        result_df, _, exec_log = build_target_scenarios(
                            mapping_path=mapping_file,
                            target_meta=build_meta,
                            output_dir=delta_output_dir,
                        )
                        pk_cols = build_meta.get("business_keys", [])

                        updated_sc, new_sc = merge_update_scenarios(prev_sc, result_df, pk_cols)

                        updated_count = len(updated_sc)
                        new_count = len(new_sc)

                    except (ValueError, FileNotFoundError) as e:
                        progress.empty()
                        st.error(f"Delta scenario generation failed: {e}")
                        st.stop()

                    new_count   = len(result_df) if result_df is not None else 0
                    total_after = len(load_scenarios_from_dir(base_scenario_dir))
                    save_mapping_snapshot(mapping, base_scenario_dir, scenario_count=total_after)

                    progress.success("✅ Cross-version scenario build complete")

                    all_rows = (
                        [{"scenario_id": s.get("scenario_id",""), "operation": s.get("operation",""),
                         "target_table": new_target, "source": "updated"} for s in updated_sc]
                        + [{"scenario_id": s.get("scenario_id",""), "operation": s.get("operation",""),
                        "target_table": new_target, "source": "new"} for s in new_sc]
                        )
                    
                    save_execution_log(exec_log, base_scenario_dir)
                    st.session_state.scenario_df              = pd.DataFrame(all_rows)
                    st.session_state.scenario_dir             = base_scenario_dir
                    st.session_state.execution_log            = exec_log
                    st.session_state.scenario_reused_count    = reused_count
                    st.session_state.scenario_new_count       = new_count
                    st.session_state.scenario_reused_from_version = prev_ver
                    st.session_state.discovered_assets        = discover_all(DATA_DIR)

                    st.markdown("### 📊 Scenario Summary")
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric(f"♻️ Reused (from {prev_ver})", reused_count)
                    col2.metric("🆕 New (delta)", new_count)
                    col3.metric("📦 Total", reused_count + new_count)
                    col4.metric("🔍 Delta Changes", len(new_cols) + len(changed_rules) + len(new_filters))
                    st.success(f"Total coverage: **{reused_count + new_count}** scenarios  "
                               f"({reused_count} from {prev_ver} + {new_count} new)")

                    if result_df is not None and not result_df.empty:
                        with st.expander(f"🆕 View {new_count} new delta scenarios", expanded=True):
                            st.dataframe(result_df.head(20), use_container_width=True)

                        if new_cols:
                            st.markdown("**New columns:** " + ", ".join(f"`{c}`" for c in new_cols))
                        if changed_rules:
                            st.markdown("**Changed transformation rules:** " + ", ".join(f"`{c}`" for c in changed_rules))
                        if new_filters:
                            st.markdown("**New filter conditions:**")
                            for f in new_filters:
                                st.code(f, language="sql")

            # ----------------------------------------------------------
            # CASE 4 — no scenarios anywhere → first ever run
            # ----------------------------------------------------------
            else:
                st.info("🆕 First-time scenario generation — no prior scenarios found")

                try:
                    result_df, _, exec_log = build_target_scenarios(
                        mapping_path=mapping_file,
                        target_meta=build_meta,
                        output_dir=base_scenario_dir,
                    )
                except (ValueError, FileNotFoundError) as e:
                    progress.empty()
                    st.error(f"Scenario generation failed: {e}")
                    st.stop()

                new_count = len(result_df) if result_df is not None else 0
                save_mapping_snapshot(mapping, base_scenario_dir, scenario_count=new_count)

                progress.success("✅ Scenario generation complete")

                save_execution_log(exec_log, base_scenario_dir)
                st.session_state.scenario_df              = result_df
                st.session_state.scenario_dir             = base_scenario_dir
                st.session_state.execution_log            = exec_log
                st.session_state.scenario_reused_count    = 0
                st.session_state.scenario_new_count       = new_count
                st.session_state.scenario_reused_from_version = None
                st.session_state.discovered_assets        = discover_all(DATA_DIR)

                if result_df is None or result_df.empty:
                    st.error("No scenarios generated")
                    st.stop()

                st.markdown("### 📊 Scenario Summary")
                col1, col2, col3 = st.columns(3)
                col1.metric("♻️ Reused", 0)
                col2.metric("🆕 New (first run)", new_count)
                col3.metric("📦 Total", new_count)

                st.markdown("### 🆕 Generated Scenarios")
                st.dataframe(result_df.head(20), use_container_width=True)

                st.success(f"🆕 Created {len(result_df)} scenarios successfully!")
                st.session_state.just_created_scenarios = True
                st.rerun()


      

# =================================================
# TAB 5 — SNOWFLAKE VALIDATION (with NL-to-SQL)
# =================================================
with tabs[4]:

    st.header("❄️ Snowflake Validation")

    # Check if Snowflake is configured
    sf_configured = all(
        os.environ.get(k) for k in ("SNOWFLAKE_USER","SNOWFLAKE_ACCOUNT")
    )
    if not sf_configured:
        st.warning("⚠️ Snowflake credentials not configured. Set SNOWFLAKE_USER, SNOWFLAKE_ACCOUNT as environment variables or HF Secrets.")

    db = st.text_input("Database", "AI_TEST")
    schema = st.text_input("Schema", "TARGET")

    target_tables = st.session_state.get("target_tables", [])
    if not target_tables:
        target_tables = ["TARGET_TRADES_VIEW"]

    default_index = 0
    last_target = st.session_state.get("last_target_table")
    if isinstance(last_target, str) and last_target in target_tables:
        default_index = target_tables.index(last_target)

    table = st.selectbox("Target Table", target_tables, index=default_index)

    # --- Resolve metadata ---
    if st.button("🔍 Resolve Metadata", key="btn_resolve_meta"):
        if not st.session_state.get("mapping_extracted"):
            st.error("Upload mapping first")
            st.stop()

        with st.spinner(ai_status("validation", 0)):
            meta = resolve_target_metadata(
                database=db, schema=schema, table=table,
                mapping=st.session_state.mapping_extracted,
            )
        st.session_state.target_meta = meta
        st.session_state.last_target_table = table
        if table not in st.session_state.target_tables:
            st.session_state.target_tables.append(table)
        st.success("✅ Metadata resolved")
        st.json(meta)

    # --- Run validation ---
    if st.button("▶️ Run Validation", key="btn_run_validation"):
        if not st.session_state.get("target_meta"):
            st.error("Resolve metadata first")
            st.stop()

        scenario_dir = st.session_state.get("scenario_dir")
        if not scenario_dir:
            st.error("Build scenarios first (Tab 3)")
            st.stop()

        scenarios = load_scenarios_from_dir(scenario_dir)
        if not scenarios:
            st.error("No scenario files found")
            st.stop()

        progress_bar = st.progress(0)
        status = st.empty()
        results = []
        target_meta = st.session_state["target_meta"]

        # Truncate target table before running scenarios (same as run_agent.py)
        try:
            conn = snowflake_connection()
            cursor = conn.cursor()
            cursor.execute(f"TRUNCATE TABLE {db}.{schema}.{table}")
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            st.warning(f"⚠️ Could not truncate table: {e}")

        for i, scenario in enumerate(scenarios):
            status.info(f"🔍 Validating scenario {i+1}/{len(scenarios)}...")
            progress_bar.progress((i + 1) / len(scenarios))

            try:
                # Normalise scenarios that use the "tables" key format
                if "tables" in scenario:
                    before = {}
                    after = {}
                    for table_data in scenario["tables"].values():
                        if table_data.get("before"):
                            before.update(table_data["before"])
                        if table_data.get("after"):
                            after.update(table_data["after"])
                    scenario_for_validation = {
                        "operation": scenario.get("operation"),
                        "before_image": before,
                        "after_image": after,
                    }
                else:
                    scenario_for_validation = scenario

                # Execute (write to Snowflake) then validate (read from Snowflake)
                execute_scenario(scenario, target_meta)
                res = validate_scenario(
                    scenario=scenario_for_validation,
                    target_meta=target_meta,
                )
                res_status = res.get("status", "FAIL")
            except Exception as e:
                res = {"status": "FAIL", "reason": str(e), "pk": None, "mismatches": []}
                res_status = "FAIL"

            results.append({
                "scenario_id": scenario.get("scenario_id"),
                "operation": scenario.get("operation"),
                "status": res_status,
                "keys": res.get("pk"),
                "reason": res.get("reason"),
                "mismatches": json.dumps(_json_safe(res.get("mismatches") or [])),
            })

        df = pd.DataFrame(results)
        st.session_state.validation_df = df
        status.success(ai_status("validation", 3))
        st.dataframe(df)

    # --- Debug: Diagnose first scenario ---
    if st.session_state.get("target_meta") and st.session_state.get("scenario_dir") and sf_configured:
        st.markdown("---")
        with st.expander("🔬 Debug: Diagnose Validation (first scenario)", expanded=False):
            if st.button("🩺 Run Diagnostic", key="btn_debug_diag"):
                scenarios = load_scenarios_from_dir(st.session_state.scenario_dir)
                if scenarios:
                    s = scenarios[0]
                    with st.spinner("Running diagnostic against Snowflake..."):
                        diag = validate_scenario_debug(s, st.session_state.target_meta)

                    st.markdown("#### 1. Target Table")
                    st.code(diag.get("full_table", "?"))

                    st.markdown("#### 2. Real Snowflake Columns")
                    real_cols = diag.get("real_snowflake_columns", [])
                    if real_cols:
                        st.success(f"Found {len(real_cols)} columns: {', '.join(real_cols)}")
                    else:
                        st.error("Could NOT fetch real columns from INFORMATION_SCHEMA!")

                    st.markdown("#### 3. Business Key Resolution")
                    bk_detail = diag.get("business_key_resolution", [])
                    st.dataframe(pd.DataFrame(bk_detail)) if bk_detail else st.warning("No business keys")

                    st.markdown("#### 4. Column Mapping (Scenario → Snowflake)")
                    col_map = diag.get("column_mapping", [])
                    if col_map:
                        df_map = pd.DataFrame(col_map)
                        unmatched = df_map[df_map["matched"] == False]
                        matched = df_map[df_map["matched"] == True]
                        st.metric("Matched", len(matched))
                        st.metric("Unmatched", len(unmatched))
                        st.dataframe(df_map)
                    else:
                        st.warning("No column mapping data")

                    st.markdown("#### 5. SQL Query")
                    st.code(diag.get("sql", "N/A"), language="sql")
                    st.write("**Params:**", diag.get("sql_params", []))

                    st.markdown("#### 6. Snowflake Response")
                    st.write(f"**Rows returned:** {diag.get('rows_returned', '?')}")
                    if diag.get("first_row"):
                        st.json(diag["first_row"])
                    if diag.get("query_error"):
                        st.error(f"Query error: {diag['query_error']}")

                    st.markdown("#### 7. Column-by-Column Comparison")
                    comps = diag.get("comparisons", [])
                    if comps:
                        df_comp = pd.DataFrame(comps)
                        st.dataframe(df_comp)
                        mismatches = diag.get("mismatches", [])
                        if mismatches:
                            st.error(f"❌ {len(mismatches)} mismatches found:")
                            st.dataframe(pd.DataFrame(mismatches))
                        else:
                            st.success("✅ All columns match!")

                    st.markdown("#### 8. Final Validation Result")
                    st.json(diag.get("validation_result", {}))
                else:
                    st.warning("No scenarios found")

    # --- Target sample preview ---
    if st.session_state.get("target_meta") and sf_configured:
        meta = st.session_state.target_meta
        st.subheader("🔍 Target Table Sample")
        query = f"SELECT * FROM {meta['database']}.{meta['schema']}.{meta['table']} LIMIT 10"
        try:
            df_preview = execute_query(sql=query, database=meta["database"], schema=meta["schema"])
            st.dataframe(df_preview)
        except Exception as e:
            st.error(str(e))

    # ----- NL to SQL (Feature 6) -----
    if ai_available() and sf_configured:
        st.markdown("---")
        st.subheader("🤖 Natural Language to SQL")
        st.caption("Ask a question in plain English and AI will generate Snowflake SQL")

        nl_question = st.text_input("💬 Ask a question about your data...", key="nl_sql_input",
                                     placeholder="e.g. Show me all trades where quantity > 1000")

        if nl_question and st.button("🔍 Generate & Run SQL", key="btn_nl_sql"):
            with st.spinner("🧠 Generating SQL..."):
                result = ai_nl_to_sql(nl_question, db, schema, table)

            if result and isinstance(result, dict):
                sql = result.get("sql", "")
                st.code(sql, language="sql")
                st.caption(f"💡 {result.get('explanation', '')} | Confidence: {result.get('confidence', '?')}%")

                if sql and st.button("▶️ Execute SQL", key="btn_exec_nl_sql"):
                    try:
                        df_result = execute_query(sql=sql, database=db, schema=schema)
                        st.dataframe(df_result)
                    except Exception as e:
                        st.error(f"Query failed: {e}")


# =================================================
# TAB 6 — COVERAGE ANALYSIS
# =================================================

with tabs[5]:

    st.header("🔬 Mapping vs Scenario — Mapping Coverage Analysis")
    st.caption("Compares what the mapping document defines against what was actually executed and covered during scenario generation.")

    exec_log     = st.session_state.get("execution_log")
    mapping_data = st.session_state.get("mapping_extracted")

    # If session exec_log is missing/empty, try loading from the saved scenario dir
    if not exec_log and st.session_state.get("scenario_dir"):
        exec_log = load_execution_log(Path(st.session_state.scenario_dir))
        if exec_log:
            st.session_state.execution_log = exec_log

    if exec_log is None or not mapping_data:
        st.info("Build scenarios first (Tab 4: Scenarios) to generate the execution log for coverage analysis.")
    else:
        # Compute gap analysis
        gap_report = compute_coverage_gap_analysis(mapping_data, exec_log)
        st.session_state.mapping_coverage = gap_report

        # ------- OVERALL COVERAGE SCORE -------
        overall = gap_report.get("overall_coverage_pct", 0)
        if overall >= 90:
            st.success(f"**Overall Mapping Coverage: {overall}%**")
        elif overall >= 70:
            st.warning(f"**Overall Mapping Coverage: {overall}%**")
        else:
            st.error(f"**Overall Mapping Coverage: {overall}%**")

        st.progress(min(overall / 100, 1.0))

        # ------- CATEGORY BREAKDOWN -------
        st.subheader("Coverage Breakdown")

        c1, c2, c3, c4, c5 = st.columns(5)

        src_pct = gap_report.get("source_tables", {}).get("coverage_pct", 0)
        join_pct = gap_report.get("joins", {}).get("coverage_pct", 0)
        filt_pct = gap_report.get("filters", {}).get("coverage_pct", 0)
        col_pct = gap_report.get("target_columns", {}).get("coverage_pct", 0)
        xform_pct = gap_report.get("transformations", {}).get("coverage_pct", 0)

        c1.metric("Source Tables", f"{src_pct}%",
                   delta=f"{gap_report['source_tables']['loaded']}/{gap_report['source_tables']['expected']}")
        c2.metric("Joins", f"{join_pct}%",
                   delta=f"{gap_report['joins']['executed']}/{gap_report['joins']['total']}")
        c3.metric("Filters", f"{filt_pct}%",
                   delta=f"{gap_report['filters']['testable']}/{gap_report['filters']['total']}")
        c4.metric("Target Columns", f"{col_pct}%",
                   delta=f"{gap_report['target_columns']['resolved']}/{gap_report['target_columns']['total']}")
        c5.metric("Transformations", f"{xform_pct}%")

        # ------- GAPS FOUND -------
        gap_summary = gap_report.get("gap_summary", {})
        total_gaps = gap_summary.get("total", 0)

        if total_gaps == 0:
            st.success("**No coverage gaps detected!** All mapping functionality is covered by scenarios.")
        else:
            st.markdown("---")
            st.subheader(f"Gaps Detected: {total_gaps}")

            gc1, gc2, gc3, gc4 = st.columns(4)
            crit = gap_summary.get("critical", 0)
            high = gap_summary.get("high", 0)
            med = gap_summary.get("medium", 0)
            low = gap_summary.get("low", 0)

            gc1.metric("Critical", crit, delta=None)
            gc2.metric("High", high, delta=None)
            gc3.metric("Medium", med, delta=None)
            gc4.metric("Low", low, delta=None)

            # Display gaps grouped by category
            all_gaps = gap_report.get("gaps", [])

            for category in ["Source Table", "Join", "Filter", "Target Column", "Transformation", "Data Quality"]:
                cat_gaps = [g for g in all_gaps if g["category"] == category]
                if not cat_gaps:
                    continue

                with st.expander(f"{'🔴' if any(g['risk'] in ('critical','high') for g in cat_gaps) else '🟡' if any(g['risk']=='medium' for g in cat_gaps) else '🟢'} {category} — {len(cat_gaps)} gap(s)", expanded=any(g["risk"] in ("critical", "high") for g in cat_gaps)):
                    for g in cat_gaps:
                        risk_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(g["risk"], "⚪")
                        st.markdown(f"{risk_icon} **{g['item']}** — `{g['risk'].upper()}`")
                        st.caption(g["detail"])
                        st.info(f"💡 {g['recommendation']}")

        # ------- JOIN EXECUTION DETAIL -------
        join_details = gap_report.get("joins", {}).get("details", [])
        if join_details:
            st.markdown("---")
            st.subheader("Join Execution Trace")

            for jd in join_details:
                status_icon = "✅" if jd["status"] == "executed" and jd["risk"] == "none" else "⚠️" if jd["status"] == "executed" else "❌"
                risk_color = {"none": "green", "low": "blue", "medium": "orange", "high": "red"}.get(jd.get("risk", ""), "gray")

                with st.container(border=True):
                    jc1, jc2, jc3 = st.columns([2, 1, 2])
                    with jc1:
                        st.markdown(f"{status_icon} **{jd['type']} JOIN** — {jd.get('tables', '')}")
                    with jc2:
                        if jd.get("rows_before") is not None:
                            st.caption(f"Rows: {jd['rows_before']} → {jd['rows_after']}")
                    with jc3:
                        st.markdown(f":{risk_color}[{jd.get('note', '')}]")

        # ------- TARGET COLUMN DETAIL -------
        col_details = gap_report.get("target_columns", {}).get("details", [])
        if col_details:
            st.markdown("---")
            st.subheader("Target Column Resolution")

            col_rows = []
            for cd in col_details:
                col_rows.append({
                    "Column": cd["column"],
                    "Rule": cd["rule"][:50],
                    "Type": cd["type"],
                    "Resolved": "✅" if cd["resolved"] else "❌",
                    "Sample": cd.get("sample_value") or "—",
                })

            st.dataframe(pd.DataFrame(col_rows), use_container_width=True)

        # ------- FILTER DETAIL -------
        filter_details = gap_report.get("filters", {}).get("details", [])
        if filter_details:
            st.markdown("---")
            st.subheader("Filter Coverage")

            for fd in filter_details:
                icon = "✅" if fd["testable"] else "❌"
                st.markdown(f"{icon} `{fd['expression'][:80]}`")
                st.caption(fd["note"])

        # ------- DATA PIPELINE FLOW -------
        row_counts = gap_report.get("row_counts", {})
        dedup = gap_report.get("deduplication", {})
        scenarios = gap_report.get("scenarios", {})

        if row_counts:
            st.markdown("---")
            st.subheader("Data Pipeline Flow")

            driver_name = row_counts.get("driving_table_name", "driving table")
            driver_rows = row_counts.get("driving_table", "?")
            after_joins = row_counts.get("after_joins", "?")
            final_rows = row_counts.get("final", "?")

            flow_parts = [f"**{driver_name}**: {driver_rows} rows"]
            flow_parts.append(f"After Joins: {after_joins} rows")
            if dedup and dedup.get("removed", 0) > 0:
                flow_parts.append(f"After Dedup: {dedup['after']} rows (removed {dedup['removed']} duplicates)")
            flow_parts.append(f"Final: {final_rows} rows")

            if scenarios:
                flow_parts.append(
                    f"Scenarios: {scenarios.get('inserts', 0)} inserts + "
                    f"{scenarios.get('updates', 0)} updates + "
                    f"{scenarios.get('deletes', 0)} deletes = "
                    f"{scenarios.get('total', 0)} total"
                )

            for i, part in enumerate(flow_parts):
                st.markdown(f"{'➡️' if i > 0 else '🏁'} {part}")

        # ------- RAW JSON (collapsible) -------
        with st.expander("📄 View Raw Gap Analysis JSON", expanded=False):
            st.json(gap_report)



# =================================================
# TAB 7 — DASHBOARD (FINAL INTERACTIVE VERSION)
# =================================================
with tabs[6]:

    st.header("📊 Validation Dashboard")

    df = st.session_state.get("validation_df")

    # =================================================
    # 🚨 PRE-CHECKS
    # =================================================
    if df is None:
        st.info("Run Snowflake validation first (Validation Tab)")
        st.stop()

    if not isinstance(df, pd.DataFrame):
        st.warning("Validation not ready")
        st.stop()

    if df.shape[0] == 0:
        st.warning("Validation ran but returned no rows")
        st.stop()

    if "status" not in df.columns:
        st.error("Validation results missing 'status' column")
        st.stop()

    # =================================================
    # ⚙️ FRAMEWORK HEALTH (PYTEST)
    # =================================================
    #'''st.subheader("⚙️ Framework Health")

    #col_btn, col_status = st.columns([1, 3])

    #with col_btn:
       # run_tests = st.button("🧪 Run Tests")

    #with col_status:
       # if run_tests:
          #  with st.spinner("Running pytest..."):

               # import subprocess, sys
#
               # result = subprocess.run(
               #     [sys.executable, "-m", "pytest", "tests/", "-q"],
                #    capture_output=True,
                #    text=True
              #  )

            #if "failed" in result.stdout.lower():
           #     st.error("❌ Some tests failed")
           #     st.code(result.stdout)
           # else:
           #     st.success("✅ All tests passed")

        #else:
           # st.caption("Run framework regression tests")

   # st.markdown("---")'''

    # =================================================
    # 🧪 VALIDATION METRICS
    # =================================================
    total = len(df)
    passed = (df["status"] == "PASS").sum()
    failed = (df["status"] == "FAIL").sum()
    skipped = (df["status"] == "SKIPPED").sum()

    success_pct = round((passed / max(total, 1)) * 100, 2)

    st.subheader("🧪 Scenario Validation Summary")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total", total)
    c2.metric("Passed", passed, delta=f"{success_pct}%")
    c3.metric("Failed", failed)
    c4.metric("Skipped", skipped)

    st.progress(success_pct / 100)
    st.caption(f"Success Rate: **{success_pct}%**")

    st.markdown("---")

    # =================================================
    # 📊 STATUS CHART
    # =================================================
    st.subheader("📊 Status Distribution")

    chart_data = df["status"].value_counts()
    st.bar_chart(chart_data)

    st.markdown("---")

    # =================================================
    # 📄 VALIDATION TABLE (INTERACTIVE)
    # =================================================
    st.subheader("📄 Validation Results")

    status_filter = st.multiselect(
        "Filter by Status",
        options=df["status"].unique(),
        default=df["status"].unique()
    )

    filtered_df = df[df["status"].isin(status_filter)]

    st.dataframe(filtered_df, use_container_width=True)

    st.markdown("---")


    # =================================================
    # 🤖 AI REPORT
    # =================================================
    if ai_available():

        st.subheader("🤖 AI Test Report")

        if st.button("📝 Generate Report"):

            with st.spinner("Generating report..."):

                session_data = build_session_context()

                for t, tdf in st.session_state.get("profiled_tables", {}).items():
                    session_data.setdefault("profiling_details", {})[t] = {
                        "rows": len(tdf),
                        "columns": list(tdf.columns),
                    }

                report = ai_generate_report(session_data)
                st.session_state.ai_report = report

        if st.session_state.get("ai_report"):
    
            st.markdown(st.session_state.ai_report)
    
            st.download_button(
                "📥 Download Report",
                str(st.session_state.ai_report),
                file_name="AI_test_report.md",
                mime="text/markdown",
            )

# =================================================
# TAB 8 — FAILED SCENARIOS (with AI Root Cause)
# =================================================
with tabs[7]:

    st.header("🔎 Failed Scenario Analysis")

    df = st.session_state.get("validation_df")

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        st.info("Run validation first (Tab 4)")
        st.stop()

    if "status" not in df.columns:
        st.info("Validation not ready")
        st.stop()

    failed_df = df[df["status"] == "FAIL"]

    if failed_df.empty:
        st.success("🎉 No failures! All scenarios passed.")
        st.stop()

    st.metric("Failed Scenarios", len(failed_df))

    for idx, row in failed_df.iterrows():
        with st.expander(f"❌ {row.get('operation')} | {row.get('keys')}"):

            st.write("**Reason:**", row.get("reason"))

            mismatches = json.loads(row.get("mismatches") or "[]")
            if mismatches:
                st.dataframe(pd.DataFrame(mismatches))

            # ----- AI Root Cause (Feature 4) -----
            if ai_available():
                if st.button(f"🤖 Why did this fail?", key=f"rca_{idx}"):
                    with st.spinner("🧠 Analyzing root cause..."):
                        scenario_data = {
                            "scenario_id": row.get("scenario_id"),
                            "operation": row.get("operation"),
                            "keys": row.get("keys"),
                        }
                        val_result = {
                            "status": row.get("status"),
                            "reason": row.get("reason"),
                            "mismatches": mismatches,
                        }
                        analysis = ai_root_cause_analysis(
                            scenario_data,
                            val_result,
                            st.session_state.get("mapping_extracted"),
                        )
                    if analysis:
                        st.markdown("### 🤖 AI Root Cause Analysis")
                        st.markdown(analysis)