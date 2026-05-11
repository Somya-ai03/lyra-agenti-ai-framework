import re
from typing import Dict, Any, List


# -------------------------------------------------
# CASE / WHEN extraction
# -------------------------------------------------
def extract_case_branches(expr: str):
    if not expr or not isinstance(expr, str):
        return set()

    expr = expr.upper()
    branches = set(re.findall(r"WHEN\s+(.*?)\s+THEN", expr))

    if "ELSE" in expr:
        branches.add("ELSE")

    return set(b.strip() for b in branches)


# -------------------------------------------------
# DEEP GAP ANALYSIS
# Uses execution_log from build_target_scenarios()
# -------------------------------------------------
def compute_coverage_gap_analysis(
    mapping: Dict[str, Any],
    execution_log: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Perform deep coverage gap analysis comparing the mapping document
    definition against what was actually executed during scenario generation.

    Returns a structured report with:
      - Overall coverage %
      - Per-category breakdown (joins, filters, columns, transformations)
      - Gap details with risk levels and recommendations
      - Summary of what's testable vs. not
    """

    gaps = []           # list of gap dicts
    covered = []        # list of covered items

    # ========================================
    # 1. SOURCE TABLE COVERAGE
    # ========================================
    src_info = execution_log.get("source_tables", {})
    expected_tables = src_info.get("expected", [])
    loaded_tables = [t["table"] for t in src_info.get("loaded", [])]
    missing_tables = src_info.get("missing", [])

    src_table_pct = round(len(loaded_tables) / max(len(expected_tables), 1) * 100, 1)

    source_table_details = []
    for t in expected_tables:
        if t in loaded_tables:
            info = next((x for x in src_info.get("loaded", []) if x["table"] == t), {})
            source_table_details.append({
                "table": t,
                "status": "loaded",
                "rows": info.get("rows", 0),
                "columns": info.get("columns", 0),
            })
            covered.append(f"Source table {t} loaded ({info.get('rows', '?')} rows)")
        else:
            source_table_details.append({
                "table": t,
                "status": "missing",
                "rows": 0, "columns": 0,
            })
            gaps.append({
                "category": "Source Table",
                "item": t,
                "risk": "critical",
                "detail": f"Source table {t} defined in mapping but could not be loaded",
                "recommendation": f"Upload and profile {t} data file",
            })

    # ========================================
    # 2. JOIN COVERAGE
    # ========================================
    join_entries = execution_log.get("joins", [])
    total_joins = len(join_entries)
    executed_joins = [j for j in join_entries if j.get("status") == "executed"]
    failed_joins = [j for j in join_entries if j.get("status") == "not_executed"]

    join_pct = round(len(executed_joins) / max(total_joins, 1) * 100, 1) if total_joins > 0 else 100.0

    join_details = []
    for j in join_entries:
        detail = {
            "type": j.get("type", "INNER"),
            "sql": j.get("sql", "")[:80],
            "status": j.get("status", "unknown"),
            "rows_before": j.get("rows_before"),
            "rows_after": j.get("rows_after"),
            "risk": j.get("risk", "unknown"),
            "note": j.get("note", ""),
            "tables": j.get("tables_joined", ""),
        }
        join_details.append(detail)

        if j.get("status") == "executed":
            risk = j.get("risk", "none")
            if risk in ("high", "medium"):
                gaps.append({
                    "category": "Join",
                    "item": f"{j.get('type', '')} JOIN — {j.get('tables_joined', '')}",
                    "risk": risk,
                    "detail": j.get("note", ""),
                    "recommendation": (
                        "INNER JOIN dropped significant rows — some source data is not testable. "
                        "Consider using LEFT JOIN or enriching reference data."
                        if "dropped" in j.get("note", "")
                        else "LEFT JOIN caused row explosion — scenarios may have duplicates. "
                             "Business key deduplication applied."
                    ),
                })
            else:
                covered.append(f"{j.get('type', '')} JOIN {j.get('tables_joined', '')} — OK")

        elif j.get("status") == "not_executed":
            gaps.append({
                "category": "Join",
                "item": f"{j.get('type', '')} JOIN (not executed)",
                "risk": "high",
                "detail": j.get("note", "JOIN defined in mapping but not executed"),
                "recommendation": "This join's table data may be missing. Upload the required source data.",
            })

    # ========================================
    # 3. FILTER COVERAGE
    # ========================================
    filter_entries = execution_log.get("filters", [])
    total_filters = len(filter_entries)
    testable_filters = [f for f in filter_entries if f.get("testable")]
    gap_filters = [f for f in filter_entries if not f.get("testable")]

    filter_pct = round(len(testable_filters) / max(total_filters, 1) * 100, 1) if total_filters > 0 else 100.0

    filter_details = []
    for f in filter_entries:
        filter_details.append({
            "expression": f.get("expression", ""),
            "status": f.get("status", "unknown"),
            "testable": f.get("testable", False),
            "note": f.get("note", ""),
            "columns_referenced": f.get("columns_referenced", []),
            "columns_found": f.get("columns_found_in_data", []),
        })

        if f.get("testable"):
            covered.append(f"Filter: {f.get('expression', '')[:60]}")
        else:
            gaps.append({
                "category": "Filter",
                "item": f.get("expression", "")[:80],
                "risk": "medium",
                "detail": f.get("note", "Filter columns not found in data"),
                "recommendation": "Filter references columns not present in joined data. "
                                  "The filter condition cannot be validated in scenarios.",
            })

    # ========================================
    # 4. TARGET COLUMN COVERAGE
    # ========================================
    col_entries = execution_log.get("target_columns", [])
    total_target_cols = len(col_entries)
    resolved_cols = [c for c in col_entries if c.get("resolved")]
    unresolved_cols = [c for c in col_entries if not c.get("resolved")]

    col_pct = round(len(resolved_cols) / max(total_target_cols, 1) * 100, 1) if total_target_cols > 0 else 100.0

    col_details = []
    for c in col_entries:
        col_details.append({
            "column": c.get("column", ""),
            "rule": c.get("rule", ""),
            "type": c.get("type", ""),
            "resolved": c.get("resolved", False),
            "sample_value": c.get("sample_value"),
            "status": c.get("status", "unknown"),
        })

        if c.get("resolved"):
            covered.append(f"Target column {c['column']} → {c.get('type', '')} ({c.get('sample_value', '')})")
        else:
            risk = "high" if c.get("type") != "System generated" else "low"
            gaps.append({
                "category": "Target Column",
                "item": c.get("column", ""),
                "risk": risk,
                "detail": f"Column {c['column']} ({c.get('type', '')}) could not be resolved from source data. Rule: {c.get('rule', '')}",
                "recommendation": (
                    "System-generated column — expected to be populated by ETL, not source data."
                    if c.get("type") == "System generated"
                    else f"Check if source data has the column referenced in rule: {c.get('rule', '')}"
                ),
            })

    # ========================================
    # 5. TRANSFORMATION COVERAGE (CASE/WHEN)
    # ========================================
    target_col_mapping = mapping.get("target_columns", {}) or mapping.get("column_mapping", {}) or {}
    total_branches = 0
    covered_branches = 0
    transformation_details = {}

    for tgt_col, logic in target_col_mapping.items():
        branches = extract_case_branches(str(logic))
        if not branches:
            continue

        total_branches += len(branches)

        # Check if this column was resolved (meaning at least some branches are covered)
        col_resolved = any(
            c.get("column") == tgt_col and c.get("resolved")
            for c in col_entries
        )

        if col_resolved:
            covered_branches += len(branches)
            transformation_details[tgt_col] = {
                "branches": sorted(branches),
                "covered_count": len(branches),
                "total_count": len(branches),
                "status": "covered",
            }
            covered.append(f"CASE/WHEN for {tgt_col}: {len(branches)} branches")
        else:
            transformation_details[tgt_col] = {
                "branches": sorted(branches),
                "covered_count": 0,
                "total_count": len(branches),
                "status": "gap",
            }
            gaps.append({
                "category": "Transformation",
                "item": f"CASE/WHEN in {tgt_col}",
                "risk": "medium",
                "detail": f"{len(branches)} CASE branches not testable — column not resolved",
                "recommendation": f"Ensure source data covers all CASE branches: {sorted(branches)}",
            })

    transform_pct = round(covered_branches / max(total_branches, 1) * 100, 1) if total_branches > 0 else 100.0

    # ========================================
    # 6. DEDUPLICATION INFO
    # ========================================
    dedup = execution_log.get("deduplication", {})
    if dedup and dedup.get("removed", 0) > 0:
        gaps.append({
            "category": "Data Quality",
            "item": "Row Deduplication",
            "risk": "low",
            "detail": f"Removed {dedup['removed']} duplicate rows after LEFT JOINs ({dedup['before']} → {dedup['after']})",
            "recommendation": "Duplicates from LEFT JOIN row explosion were deduplicated on business keys. Scenarios use unique rows.",
        })

    # ========================================
    # 7. OVERALL COVERAGE
    # ========================================
    components = [src_table_pct, join_pct, filter_pct, col_pct, transform_pct]
    overall_pct = round(sum(components) / len(components), 1)

    # Count risks
    critical_gaps = [g for g in gaps if g["risk"] == "critical"]
    high_gaps = [g for g in gaps if g["risk"] == "high"]
    medium_gaps = [g for g in gaps if g["risk"] == "medium"]
    low_gaps = [g for g in gaps if g["risk"] == "low"]

    return {
        "overall_coverage_pct": overall_pct,

        "source_tables": {
            "coverage_pct": src_table_pct,
            "expected": len(expected_tables),
            "loaded": len(loaded_tables),
            "missing": len(missing_tables),
            "details": source_table_details,
        },

        "joins": {
            "coverage_pct": join_pct,
            "total": total_joins,
            "executed": len(executed_joins),
            "not_executed": len(failed_joins),
            "details": join_details,
        },

        "filters": {
            "coverage_pct": filter_pct,
            "total": total_filters,
            "testable": len(testable_filters),
            "gaps": len(gap_filters),
            "details": filter_details,
        },

        "target_columns": {
            "coverage_pct": col_pct,
            "total": total_target_cols,
            "resolved": len(resolved_cols),
            "unresolved": len(unresolved_cols),
            "details": col_details,
        },

        "transformations": {
            "coverage_pct": transform_pct,
            "total_branches": total_branches,
            "covered_branches": covered_branches,
            "details": transformation_details,
        },

        "scenarios": execution_log.get("scenarios_generated", {}),
        "row_counts": execution_log.get("row_counts", {}),
        "deduplication": dedup,

        "gaps": gaps,
        "covered": covered,
        "gap_summary": {
            "total": len(gaps),
            "critical": len(critical_gaps),
            "high": len(high_gaps),
            "medium": len(medium_gaps),
            "low": len(low_gaps),
        },
    }


# -------------------------------------------------
# LEGACY FUNCTION (kept for backward compatibility)
# -------------------------------------------------
def compute_mapping_coverage(mapping: Dict[str, Any], scenario_df):
    """
    Mapping coverage is LOGIC coverage, not dataframe-column coverage.
    Legacy function — use compute_coverage_gap_analysis() for deep analysis.
    """

    scenario_count = len(scenario_df) if scenario_df is not None else 0

    target_columns = list(
        (mapping.get("column_mapping") or {}).keys()
        or mapping.get("target_columns", [])
        or []
    )

    if scenario_count > 0:
        covered_target_columns = target_columns
        missing_target_columns = []
    else:
        covered_target_columns = []
        missing_target_columns = target_columns

    target_column_coverage_pct = (
        round((len(covered_target_columns) / len(target_columns)) * 100, 2)
        if target_columns else 100.0
    )

    joins = mapping.get("joins", [])
    join_count = len(joins)
    join_coverage_pct = 100.0 if join_count > 0 and scenario_count > 0 else 0.0

    filters = mapping.get("filters", [])
    filter_count = len(filters)
    filter_coverage_pct = 100.0 if filter_count > 0 and scenario_count > 0 else 0.0

    filter_details = [
        {"expression": f, "covered": scenario_count > 0}
        for f in filters
    ]

    transformations = mapping.get("column_mapping", {}) or {}
    total_branches = 0
    covered_branches = 0
    transformation_details = {}

    for tgt_col, logic in transformations.items():
        branches = extract_case_branches(logic)
        if not branches:
            continue

        total_branches += len(branches)
        covered_branches += len(branches)

        transformation_details[tgt_col] = {
            "branches": sorted(branches),
            "covered": True
        }

    transformation_coverage_pct = (
        round((covered_branches / total_branches) * 100, 2)
        if total_branches > 0 else 100.0
    )

    components = [
        target_column_coverage_pct,
        join_coverage_pct,
        filter_coverage_pct,
        transformation_coverage_pct
    ]

    overall_mapping_coverage_pct = round(sum(components) / len(components), 2)

    return {
        "target_column_coverage_pct": target_column_coverage_pct,
        "target_columns": target_columns,
        "covered_target_columns": covered_target_columns,
        "missing_target_columns": missing_target_columns,
        "join_coverage_pct": join_coverage_pct,
        "join_count": join_count,
        "filter_coverage_pct": filter_coverage_pct,
        "filter_count": filter_count,
        "filters": filter_details,
        "transformation_coverage_pct": transformation_coverage_pct,
        "transformation_details": transformation_details,
        "overall_mapping_coverage_pct": overall_mapping_coverage_pct,
    }
