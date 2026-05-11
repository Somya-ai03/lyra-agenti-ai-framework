import pandas as pd

from core.profiling.profiler_engine import (
    dataset_overview,
    detect_column_types,
    column_statistics,
    value_distribution,
    pattern_detection,
    detect_column_roles,
    pattern_coverage,
    generate_pattern_buckets,
    select_coverage_rows,
    compute_coverage_metrics,
    build_profiler_output,
    profiling_report,
    detect_variance_patterns,
    ensure_recordid

)

print("SCRIPT STARTED")

# ----------------------------
# Raw file path
# ----------------------------

RAW_FILE_PATH = "/Users/somyak/projects/My-AI-project/lyra-agentic-ai-framework/data/raw/SRC_ORDERS.csv"

df = pd.read_csv(RAW_FILE_PATH)

df = ensure_recordid(df)


def normalize_datetime_columns(df):
    """
    Convert timestamp-like columns to datetime
    """

    for col in df.columns:

        if "ts" in col.lower() or "timestamp" in col.lower() or "date" in col.lower():

            try:
                df[col] = pd.to_datetime(df[col])
            except:
                pass

    return df


def run_profiler():

    print("\nLoading raw dataset...")

    df = pd.read_csv(RAW_FILE_PATH)

    # Normalize datetime columns
    df = normalize_datetime_columns(df)

    results = {}

    print("\nStep 1: Dataset Overview")
    overview = dataset_overview(df)
    print(overview)
    results["overview"] = overview

    print("\nStep 2: Column Types")
    column_types = detect_column_types(df)
    print(column_types)
    results["column_types"] = column_types

    print("\nStep 3: Column Statistics")
    stats = column_statistics(df, column_types)
    print(stats)
    results["column_statistics"] = stats

    print("\nStep 4: Value Distribution")
    distribution = value_distribution(df, column_types)
    print(distribution)
    results["value_distribution"] = distribution

    print("\nStep 5: Pattern Detection")
    patterns = pattern_detection(df, column_types)
    print(patterns)

    results["patterns"] = patterns

    print("\nStep 6: Column Role Detection")
    roles = detect_column_roles(df, column_types)
    print(roles)

    results["column_roles"] = roles

    print("\nStep 7: Pattern Coverage Check")

    sample_df = df.sample(n=100)

    coverage = pattern_coverage(patterns, sample_df)

    print(coverage)

    results["coverage"] = coverage

    print("\nStep 8: Generate Pattern Buckets")

    buckets = generate_pattern_buckets(df, column_types, roles)

    print(buckets)

    results["pattern_buckets"] = buckets    

    # Step 8
    print("\nStep 9: Select Coverage Rows")
    coverage_rows = select_coverage_rows(df, buckets, column_types)

    print("\nStep 9.5: Variance Detection")

    variance_explanations = detect_variance_patterns(
    df,
    coverage_rows,
    column_types    
    )

    # Step 9
    print("\nStep 10: Coverage Metrics")
    coverage_metrics = compute_coverage_metrics(buckets, coverage_rows, column_types)


    # Step 10
    print("\nStep 11: Profiling Report")
    results = build_profiler_output(
    overview,
    column_types,
    roles,
    stats,
    distribution,
    patterns,
    buckets,
    coverage_metrics,
    coverage_rows,
    variance_explanations
)

    report = profiling_report(results)

    print(report)

    return results


if __name__ == "__main__":
    run_profiler()