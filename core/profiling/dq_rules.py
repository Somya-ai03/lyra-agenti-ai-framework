"""
dq_rules.py

Generic Data Quality & Variance Rule Definitions
Used by AI Data Profiler for scenario generation
Aligned with ATF Profiler / PADS logic
"""

# ------------------------------------------------
# 1. Mandatory DQ Threshold Rules
# ------------------------------------------------

DQ_THRESHOLDS = {
    "null_percent_max": 0.05,
    "distinct_percent_min": 0.005,
    "distinct_percent_max": 0.95,
}

# ------------------------------------------------
# 2. Variance Rule Catalog
# ------------------------------------------------

VARIANCE_RULES = {

    "TopValue": {
        "description": "Select top-N most frequent values",
        "applicable_types": ["string", "categorical"],
        "params": {"top_n": [1, 5]}
    },

    "TopPCT": {
        "description": "Select values covering top percentage of rows",
        "applicable_types": ["string", "categorical"],
        "params": {"percentages": [80, 90]}
    },

    "Range": {
        "description": "Bucket numeric/date values into ranges",
        "applicable_types": ["numeric", "date"],
        "params": {}
    },

    "PositiveNegative": {
        "description": "Capture positive / negative / zero values",
        "applicable_types": ["numeric"],
        "params": {"include_zero": True}
    },

    "CharLength": {
        "description": "Group string values by character length",
        "applicable_types": ["string"],
        "params": {
            "ranges": [
                (1,10),
                (11,20),
                (21,50)
            ]
        }
    }
}

# ------------------------------------------------
# 3. Column Type Mapping
# ------------------------------------------------

COLUMN_TYPE_MAPPING = {
    "numeric": ["int", "float", "decimal"],
    "string": ["object", "string", "varchar", "char"],
    "categorical": ["object"],
    "date": ["date", "timestamp", "datetime"]
}

# ------------------------------------------------
# 4. Incremental Profiling Settings
# ------------------------------------------------

INCREMENTAL_PROFILING = {
    "enabled": True,
    "new_column_filter_flag": "NEW_COLUMN"
}