from __future__ import annotations

import pandas as pd
import json
from typing import Dict, Any

from core.profiling.dq_rules import (
    DQ_THRESHOLDS,
    VARIANCE_RULES,
    COLUMN_TYPE_MAPPING
)

from core.ai.ai_engine import ai_available, ai_chat


# ------------------------------------------------
# RecordId generator
# ------------------------------------------------

def ensure_recordid(df: pd.DataFrame) -> pd.DataFrame:

    df = df.copy()

    if "RecordId" not in df.columns:
        df.insert(0, "RecordId", range(1, len(df) + 1))

    return df


# ------------------------------------------------
# Column type inference
# ------------------------------------------------

def infer_column_type(dtype: str) -> str:

    d = str(dtype).lower()

    for k, values in COLUMN_TYPE_MAPPING.items():
        for v in values:
            if v in d:
                return k

    return "string"


# ------------------------------------------------
# Column profiling
# ------------------------------------------------

def compute_column_dq_metrics(df: pd.DataFrame) -> pd.DataFrame:

    rows = []
    total = len(df)

    for col in df.columns:

        if col == "RecordId":
            continue

        s = df[col]

        row = {
            "column_name": col,
            "null_percent": s.isna().mean(),
            "distinct_percent": s.nunique(dropna=True) / max(total, 1),
            "dtype": str(s.dtype),
        }

        rows.append(row)

    return pd.DataFrame(rows)


# ------------------------------------------------
# Column health
# ------------------------------------------------

def evaluate_column_health(metrics: pd.DataFrame) -> pd.DataFrame:

    df = metrics.copy()

    df["null_check"] = df["null_percent"] <= DQ_THRESHOLDS["null_percent_max"]

    df["sparse_check"] = df["distinct_percent"] >= DQ_THRESHOLDS["distinct_percent_min"]

    df["cardinality_check"] = df["distinct_percent"] <= DQ_THRESHOLDS["distinct_percent_max"]

    df["dq_status"] = (
        df["null_check"] &
        df["sparse_check"] &
        df["cardinality_check"]
    ).map({True: "PASS", False: "FAIL"})

    df["column_type"] = df["dtype"].apply(infer_column_type)

    return df


# ------------------------------------------------
# Row mask
# ------------------------------------------------

def compute_row_pass_mask(df: pd.DataFrame, column_health: pd.DataFrame):

    failed_cols = column_health[
        column_health["dq_status"] == "FAIL"
    ]["column_name"].tolist()

    if not failed_cols:
        return pd.Series(True, index=df.index)

    return ~df[failed_cols].isna().any(axis=1)


# ------------------------------------------------
# Variance rules
# ------------------------------------------------

def variance_top_values(df, col):

    vc = df[col].value_counts(dropna=True).head(5)

    return df[df[col].isin(vc.index)][["RecordId", col]].rename(
        columns={col: "value"}
    )


def variance_range(df, col):

    if not pd.api.types.is_numeric_dtype(df[col]):
        return pd.DataFrame()

    q1 = df[col].quantile(0.25)
    q3 = df[col].quantile(0.75)

    return df[(df[col] <= q1) | (df[col] >= q3)][["RecordId", col]].rename(
        columns={col: "value"}
    )


def variance_char_length(df, col):

    length = df[col].astype(str).str.len()

    return df[(length <= 5) | (length >= 20)][["RecordId", col]].rename(
        columns={col: "value"}
    )


RULE_FUNCTIONS = {
    "TopValue": variance_top_values,
    "Range": variance_range,
    "CharLength": variance_char_length
}


# ------------------------------------------------
# AI rule selection
# ------------------------------------------------

def ai_select_rules(column_name, column_type, stats):

    if not ai_available():
        return None

    try:

        prompt = f"""
Column: {column_name}
Type: {column_type}

Stats:
{json.dumps(stats)}

Available rules:
{list(RULE_FUNCTIONS.keys())}

Return JSON list of best rules.
"""

        response = ai_chat(prompt, session_context={}, chat_history=[])

        if response is None:
            return None

        return json.loads(response)

    except Exception:
        return None


# ------------------------------------------------
# Variance dataset
# ------------------------------------------------

def generate_variance_dataset(df: pd.DataFrame):

    df = ensure_recordid(df)

    metrics = compute_column_dq_metrics(df)
    health = evaluate_column_health(metrics)

    collected = []

    for _, row in health.iterrows():

        col = row["column_name"]
        col_type = row["column_type"]

        if col not in df.columns:
            continue

        if df[col].isna().all():
            continue

        stats = row.to_dict()

        ai_rules = ai_select_rules(col, col_type, stats)

        if ai_rules:
            rules = ai_rules
        else:
            rules = RULE_FUNCTIONS.keys()

        for rule_name in rules:

            fn = RULE_FUNCTIONS.get(rule_name)

            if not fn:
                continue

            try:

                out = fn(df, col)

                if out.empty:
                    continue

                out["column_name"] = col
                out["variance_type"] = rule_name

                sampled = out.drop_duplicates("value").head(5)

                collected.append(sampled)

            except Exception:
                continue

    if not collected:
        return pd.DataFrame(columns=["RecordId","column_name","value","variance_type"])

    variance_df = pd.concat(collected)

    return variance_df


# ------------------------------------------------
# Attach variance sample
# ------------------------------------------------

def attach_variance_to_sample(df: pd.DataFrame):

    df = ensure_recordid(df)

    variance_df = generate_variance_dataset(df)

    coverage_ids = set()

    if not variance_df.empty:
        coverage_ids.update(variance_df["RecordId"].tolist())

    coverage_size = max(20, min(200, int(len(df) * 0.0005)))

    ts_cols = [c for c in df.columns if "TS" in c or "DATE" in c]

    latest_ids = []
    historical_ids = []

    if ts_cols:

        ts = ts_cols[0]

        latest_ids = df.sort_values(ts, ascending=False).head(coverage_size)["RecordId"].tolist()

        historical_ids = df.sort_values(ts).head(coverage_size)["RecordId"].tolist()

        coverage_ids.update(latest_ids)
        coverage_ids.update(historical_ids)

    if len(coverage_ids) < coverage_size:

        random_ids = df.sample(min(coverage_size * 2, len(df)))["RecordId"].tolist()

        coverage_ids.update(random_ids)

    coverage_df = df[df["RecordId"].isin(coverage_ids)].copy()

    variance_map = {}

    if not variance_df.empty:

        variance_map = (
            variance_df
            .groupby("RecordId")[["column_name","variance_type","value"]]
            .apply(lambda x: x.to_dict("records"))
            .to_dict()
        )

    def build_explanation(row):

        rid = row["RecordId"]

        if rid in variance_map:
            return variance_map[rid]

        if rid in latest_ids and ts_cols:
            return [{
                "column_name": ts_cols[0],
                "variance_type": "LatestTimestamp",
                "value": str(row[ts_cols[0]])
            }]

        if rid in historical_ids and ts_cols:
            return [{
                "column_name": ts_cols[0],
                "variance_type": "HistoricalTimestamp",
                "value": str(row[ts_cols[0]])
            }]

        return [{
            "column_name": "RecordId",
            "variance_type": "CoverageSample",
            "value": int(rid)
        }]

    coverage_df["variance"] = coverage_df.apply(build_explanation, axis=1)

    coverage_df["variance"] = coverage_df["variance"].apply(
        lambda x: x if x and len(x) > 0 else [{
            "column_name": "RecordId",
            "variance_type": "CoverageSample",
            "value": None
        }]
    )

    return coverage_df.reset_index(drop=True)


# ------------------------------------------------
# Summary
# ------------------------------------------------

def dq_summary(column_health_df: pd.DataFrame, pass_mask: pd.Series) -> Dict[str, Any]:

    total = len(pass_mask)
    passed = int(pass_mask.sum())

    return {

        "rows_total": total,
        "rows_pass": passed,
        "rows_fail": total - passed,
        "pass_rate": round(passed / max(total, 1), 4),
        "columns_profiled": len(column_health_df),

        "columns_failed": int(
            (column_health_df["dq_status"] == "FAIL").sum()
        ),

        "failed_columns": column_health_df[
            column_health_df["dq_status"] == "FAIL"
        ]["column_name"].tolist()
    }