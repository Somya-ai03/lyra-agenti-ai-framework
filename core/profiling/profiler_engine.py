import pandas as pd

def ensure_recordid(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds a RecordId column if not present.
    """

    df = df.copy()

    if "RecordId" not in df.columns:
        df.insert(0, "RecordId", range(1, len(df) + 1))

    return df


def exclude_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df[[col for col in df.columns if col.lower() != "recordid"]]


def format_variance(variance_dict):
    parts = []

    for col, details in variance_dict.items():
        parts.append(f"{col}={details['variance_type']}")

    return ", ".join(parts)



def dataset_overview(df: pd.DataFrame) -> dict:
    """
    Returns basic dataset information
    """

    overview = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": list(df.columns)
    }

    return overview


def detect_column_types(df: pd.DataFrame) -> dict:
    """
    Detects column types automatically
    """

    column_types = {}

    for col in df.columns:

        dtype = df[col].dtype

        if pd.api.types.is_numeric_dtype(dtype):
            column_types[col] = "numeric"

        elif pd.api.types.is_datetime64_any_dtype(dtype):
            column_types[col] = "datetime"

        else:
            column_types[col] = "categorical"

    return column_types



def column_statistics(df: pd.DataFrame, column_types: dict) -> dict:
    """
    Computes statistics for each column depending on its detected type.
    """

    stats = {}

    for col, col_type in column_types.items():

        series = df[col]

        if col_type == "numeric":

            stats[col] = {
                "type": "numeric",
                "count": int(series.count()),
                "null_count": int(series.isna().sum()),
                "mean": float(series.mean()) if series.count() > 0 else None,
                "median": float(series.median()) if series.count() > 0 else None,
                "mode": float(series.mode().iloc[0]) if not series.mode().empty else None,
                "std_dev": float(series.std()) if series.count() > 1 else None,
                "min": float(series.min()) if series.count() > 0 else None,
                "max": float(series.max()) if series.count() > 0 else None,
                "p25": float(series.quantile(0.25)) if series.count() > 0 else None,
                "p50": float(series.quantile(0.50)) if series.count() > 0 else None,
                "p75": float(series.quantile(0.75)) if series.count() > 0 else None
            }

        elif col_type == "categorical":

            stats[col] = {
                "type": "categorical",
                "count": int(series.count()),
                "null_count": int(series.isna().sum()),
                "distinct_values": int(series.nunique(dropna=True)),
                "top_value": str(series.mode().iloc[0]) if not series.mode().empty else None
            }

        elif col_type == "datetime":

            stats[col] = {
                "type": "datetime",
                "count": int(series.count()),
                "null_count": int(series.isna().sum()),
                "min_date": str(series.min()),
                "max_date": str(series.max())
            }

    return stats



def value_distribution(df: pd.DataFrame, column_types: dict, top_n: int = 10) -> dict:
    """
    Computes value distribution for each column.
    """

    distributions = {}

    for col, col_type in column_types.items():

        series = df[col]

        if col_type in ["numeric", "categorical"]:

            value_counts = series.value_counts(dropna=True)

            distributions[col] = {
                "distinct_values": int(series.nunique(dropna=True)),
                "top_values": value_counts.head(top_n).to_dict(),
                "rare_values": value_counts[value_counts == 1].head(top_n).to_dict()
            }

    return distributions


def pattern_detection(df: pd.DataFrame, column_types: dict) -> dict:
    """
    Detects data patterns for each column.
    """

    patterns = {}

    for col, col_type in column_types.items():

        series = df[col]

        if col_type == "numeric":

            patterns[col] = {
                "has_negative": bool((series < 0).any()),
                "has_zero": bool((series == 0).any()),
                "has_positive": bool((series > 0).any())
            }

            # simple outlier detection (IQR)
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1

            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr

            outliers = series[(series < lower_bound) | (series > upper_bound)]

            patterns[col]["outliers_detected"] = len(outliers) > 0
            patterns[col]["outlier_count"] = int(len(outliers))

        elif col_type == "categorical":

            value_counts = series.value_counts()

            rare_values = value_counts[value_counts == 1]

            patterns[col] = {
                "distinct_values": int(series.nunique()),
                "rare_values_detected": len(rare_values) > 0,
                "rare_value_count": int(len(rare_values))
            }

        elif col_type == "datetime":

            patterns[col] = {
                "min_date": str(series.min()),
                "max_date": str(series.max())
            }

    return patterns


def detect_column_roles(df: pd.DataFrame, column_types: dict) -> dict:
    """
    Detects the role of each column.
    """

    roles = {}

    for col in df.columns:

        col_lower = col.lower()

        # Identifier detection
        if col_lower.endswith("_id") or col_lower == "id":
            roles[col] = "identifier"

        # Timestamp detection
        elif "date" in col_lower or "ts" in col_lower or "timestamp" in col_lower:
            roles[col] = "timestamp"

        # Everything else
        else:
            roles[col] = "business"

    return roles


def pattern_coverage(patterns: dict, df_sample: pd.DataFrame) -> dict:

    coverage = {}

    for col, info in patterns.items():

        if col not in df_sample.columns:
            continue

        column_values = df_sample[col]

        if "distinct_values" in info:

            detected_values = column_values.unique()

            coverage[col] = {
                "sample_distinct_values": len(detected_values)
            }

    return coverage


def generate_pattern_buckets(df: pd.DataFrame, column_types: dict, column_roles: dict):
    """
    Generates coverage buckets for each column.
    """

    import pandas as pd

    buckets = {}

    for col, col_type in column_types.items():

        # Skip identifier columns
        if column_roles.get(col) == "identifier":
            continue

        series = df[col]

        # -----------------------------------
        # CATEGORICAL
        # -----------------------------------
        if col_type == "categorical":

            unique_values = series.dropna().unique()

            # LIMIT for performance
            if len(unique_values) > 50:
                unique_values = unique_values[:50]

            buckets[col] = list(unique_values)

        # -----------------------------------
        # NUMERIC
        # -----------------------------------
        elif col_type == "numeric":

            bucket_list = []

            # Basic buckets
            if (series < 0).any():
                bucket_list.append("negative")

            if (series == 0).any():
                bucket_list.append("zero")

            if (series > 0).any():
                bucket_list.append("positive")

            # -----------------------------------
            # OUTLIER DETECTION (SAFE)
            # -----------------------------------
            if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):

                try:
                    q1 = series.quantile(0.25)
                    q3 = series.quantile(0.75)

                    if q1 is not None and q3 is not None:
                        iqr = q3 - q1
                        lower = q1 - 1.5 * iqr
                        upper = q3 + 1.5 * iqr

                        if ((series < lower) | (series > upper)).any():
                            bucket_list.append("outlier")

                except Exception:
                    pass  # safely ignore

            buckets[col] = bucket_list

        # -----------------------------------
        # DATETIME
        # -----------------------------------
        elif col_type == "datetime":

            buckets[col] = ["earliest_date", "latest_date"]

    return buckets

def select_coverage_rows(df, buckets, column_types):
    """
    Selects rows ensuring every pattern bucket is represented.
    """

    selected_indices = set()

    for col, bucket_values in buckets.items():

        if col not in df.columns:
            continue

        series = df[col]

        # categorical columns
        if column_types[col] == "categorical":

           for i, val in enumerate(bucket_values):

                 if i > 50:   # LIMIT
                     break

                 match = df[df[col] == val]

                 if not match.empty:
                    selected_indices.add(match.index[0])

        # numeric columns
        elif column_types[col] == "numeric":

            for rule in bucket_values:

                if rule == "negative":
                    match = df[df[col] < 0]

                elif rule == "zero":
                    match = df[df[col] == 0]

                elif rule == "positive":
                    match = df[df[col] > 0]

                elif rule == "outlier":

                    q1 = series.quantile(0.25)
                    q3 = series.quantile(0.75)
                    iqr = q3 - q1

                    lower = q1 - 1.5 * iqr
                    upper = q3 + 1.5 * iqr

                    match = df[(df[col] < lower) | (df[col] > upper)]

                else:
                    continue

                if not match.empty:
                    selected_indices.add(match.index[0])

        # datetime columns
        elif column_types[col] == "datetime":

            earliest_idx = series.idxmin()
            latest_idx = series.idxmax()

            selected_indices.add(earliest_idx)
            selected_indices.add(latest_idx)

    return df.loc[list(selected_indices)]


def compute_coverage_metrics(buckets, selected_df, column_types):
    """
    Computes coverage % of pattern buckets.
    """

    total_patterns = 0
    covered_patterns = 0

    for col, bucket_values in buckets.items():

        if col not in selected_df.columns:
            continue

        for rule in bucket_values:

            total_patterns += 1

            if column_types[col] == "categorical":

                if rule in selected_df[col].values:
                    covered_patterns += 1

            elif column_types[col] == "numeric":

                if rule == "negative" and (selected_df[col] < 0).any():
                    covered_patterns += 1

                elif rule == "zero" and (selected_df[col] == 0).any():
                    covered_patterns += 1

                elif rule == "positive" and (selected_df[col] > 0).any():
                    covered_patterns += 1

                elif rule == "outlier":
                    covered_patterns += 1

            elif column_types[col] == "datetime":

                covered_patterns += 1

    coverage_pct = 0

    if total_patterns > 0:
        coverage_pct = round((covered_patterns / total_patterns) * 100, 2)

    return {
        "total_patterns": total_patterns,
        "covered_patterns": covered_patterns,
        "coverage_percent": coverage_pct
    }


def detect_variance_patterns(df, selected_rows, column_types, buckets):

    explanations = {}

    for idx, row in selected_rows.iterrows():

        rid = int(row.get("RecordId", idx))
        row_variance = {}

        for col, col_type in column_types.items():

            if col == "RecordId":
                continue

            val = row[col]

            if pd.isna(val):
                continue

            # ---------------------
            # NUMERIC
            # ---------------------
            if col_type == "numeric":

                if val < 0:
                    row_variance[col] = "negative"

                elif val == 0:
                    row_variance[col] = "zero"

                else:
                    row_variance[col] = "positive"

                # outlier check
                try:
                    q1 = df[col].quantile(0.25)
                    q3 = df[col].quantile(0.75)
                    iqr = q3 - q1

                    lower = q1 - 1.5 * iqr
                    upper = q3 + 1.5 * iqr

                    if val < lower or val > upper:
                        row_variance[col] = "outlier"
                except:
                    pass

            # ---------------------
            # CATEGORICAL
            # ---------------------
            elif col_type == "categorical":

                freq = df[col].value_counts().get(val, 0)

                if freq == 1:
                    row_variance[col] = "rare_value"
                else:
                    row_variance[col] = "common_value"

            # ---------------------
            # DATETIME
            # ---------------------
            elif col_type == "datetime":

                if val == df[col].min():
                    row_variance[col] = "earliest_date"

                elif val == df[col].max():
                    row_variance[col] = "latest_date"

                else:
                    row_variance[col] = "normal_date"

        explanations[rid] = row_variance

    return explanations


def attach_variance_column(selected_rows, variance_explanations):

    variance_col = []

    for idx, row in selected_rows.iterrows():

        rid = int(row.get("RecordId", idx))
        variance_dict = variance_explanations.get(rid, {})

        formatted = ", ".join(
            [f"{col}={v}" for col, v in variance_dict.items()]
        )

        variance_col.append(formatted)

    selected_rows["Variance"] = variance_col

    return selected_rows


def build_profiler_output(
    overview,
    column_types,
    roles,
    stats,
    distributions,
    patterns,
    buckets,
    coverage_metrics,
    selected_rows,
    variance_explanations
):

    return {
        "dataset_overview": overview,
        "column_types": column_types,
        "column_roles": roles,
        "statistics": stats,
        "distributions": distributions,
        "patterns": patterns,
        "pattern_buckets": buckets,
        "coverage_metrics": coverage_metrics,
        "selected_row_count": len(selected_rows),
        "variance_explanations": variance_explanations
    }







def profiling_report(results):

    report = {}

    report["rows"] = results["dataset_overview"]["row_count"]
    report["columns"] = results["dataset_overview"]["column_count"]

    coverage = results["coverage_metrics"]

    report["patterns_detected"] = coverage["total_patterns"]
    report["patterns_covered"] = coverage["covered_patterns"]
    report["coverage_percent"] = coverage["coverage_percent"]

    report["sample_rows_generated"] = results["selected_row_count"]

    return report