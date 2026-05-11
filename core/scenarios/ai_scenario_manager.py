from typing import Dict, List, Any, Optional
import hashlib
import json
from pathlib import Path
from datetime import datetime


# ------------------------------------------------
# Normalize logic into comparable blocks
# ------------------------------------------------

def normalize_mapping(mapping):

    blocks = []

    for col in mapping.get("target_columns", {}).keys():
        blocks.append({
            "type": "column",
            "value": col
        })

    return blocks

# ------------------------------------------------
# Convert scenario into comparable blocks
# ------------------------------------------------

def normalize_scenarios(scenarios):

    blocks = []

    for sc in scenarios:

        metadata = sc.get("metadata", {})

        # 🔥 COLUMNS (match mapping format)
        for col in metadata.get("target_columns", []):
            blocks.append({
                "type": "column",
                "value": col   # keep simple OR upgrade below
            })

        # 🔥 JOINS
        for join in metadata.get("joins", []):
            blocks.append({
                "type": "join",
                "value": str(join.get("keys", []))
            })

        # 🔥 FILTERS
        for f in metadata.get("filters", []):
            blocks.append({
                "type": "filter",
                "value": f.strip()
            })

    return blocks


# ------------------------------------------------
# Hash helper (generic comparison)
# ------------------------------------------------

def hash_block(block: Dict[str, Any]) -> str:
    return hashlib.md5(str(block).encode()).hexdigest()


# ------------------------------------------------
# MAIN AI MANAGER
# ------------------------------------------------

def analyze_changes(mapping: Dict[str, Any], scenarios: List[Dict[str, Any]]) -> Dict[str, List]:

    mapping_blocks = normalize_mapping(mapping)
    scenario_blocks = normalize_scenarios(scenarios)

    mapping_hashes = {hash_block(b): b for b in mapping_blocks}
    scenario_hashes = {hash_block(b): b for b in scenario_blocks}

    result = {
        "reuse": [],
        "create": [],
        "update": []
    }

    # Detect NEW or EXISTING
    for h, block in mapping_hashes.items():

        if h in scenario_hashes:
            result["reuse"].append(block)
        else:
            result["create"].append(block)

    # Detect REMOVED / NEED UPDATE
    for h, block in scenario_hashes.items():

        if h not in mapping_hashes:
            result["update"].append(block)

    return result


# ------------------------------------------------
# Mapping snapshot — persist & compare across runs
# ------------------------------------------------

def _compute_mapping_hash(mapping: Dict[str, Any]) -> str:
    """
    Deterministic hash of the mapping's full logical state:
    column names + transformation rules + joins + filters.
    """
    state = {
        # column name + its transformation rule — catches rule changes even when names stay the same
        "column_rules": sorted(
            f"{k}={v}" for k, v in mapping.get("target_columns", {}).items()
        ),
        "joins": sorted(str(j.get("keys", [])) for j in mapping.get("joins", [])),
        "filters": sorted(str(f).strip() for f in mapping.get("filters", [])),
    }
    return hashlib.md5(json.dumps(state, sort_keys=True).encode()).hexdigest()


def save_mapping_snapshot(mapping: Dict[str, Any], scenario_dir: Path, scenario_count: int = 0) -> Dict:
    """
    Save a mapping fingerprint next to the scenarios so future runs can detect changes.
    Persists column names, transformation rules, joins, and filters.
    Written to: {scenario_dir}/mapping_snapshot.json
    """
    snapshot = {
        "mapping_hash": _compute_mapping_hash(mapping),
        # column names (for name-level add/remove detection)
        "target_columns": sorted(mapping.get("target_columns", {}).keys()),
        # column name + rule (for transformation rule change detection)
        "column_rules": sorted(
            f"{k}={v}" for k, v in mapping.get("target_columns", {}).items()
        ),
        "joins": [str(j.get("keys", [])) for j in mapping.get("joins", [])],
        "filters": [str(f).strip() for f in mapping.get("filters", [])],
        "generated_at": datetime.now().isoformat(),
        "scenario_count": scenario_count,
    }
    snapshot_path = Path(scenario_dir) / "mapping_snapshot.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w") as fh:
        json.dump(snapshot, fh, indent=2)
    print(f"💾 Mapping snapshot saved → {snapshot_path}")
    return snapshot


def load_mapping_snapshot(scenario_dir: Path) -> Optional[Dict]:
    """Load the saved mapping snapshot for a scenario directory, or None if absent."""
    snapshot_path = Path(scenario_dir) / "mapping_snapshot.json"
    if not snapshot_path.exists():
        return None
    with open(snapshot_path) as fh:
        return json.load(fh)


def get_mapping_changes(mapping: Dict[str, Any], snapshot: Optional[Dict]) -> Dict:
    """
    Compare current mapping against a saved snapshot.

    Returns a dict with:
      - has_changes (bool)
      - is_first_run (bool) — True when no snapshot exists
      - new_columns       — column names added
      - removed_columns   — column names removed
      - changed_rules     — columns whose transformation rule changed (name present in both,
                            but rule text differs)
      - new_filters       — filter/condition strings added
      - removed_filters   — filter/condition strings removed
      - new_joins         — join keys added
      - removed_joins     — join keys removed
    """
    if snapshot is None:
        return {
            "has_changes": True,
            "is_first_run": True,
            "new_columns": list(mapping.get("target_columns", {}).keys()),
            "new_joins": [str(j.get("keys", [])) for j in mapping.get("joins", [])],
            "new_filters": [str(f).strip() for f in mapping.get("filters", [])],
            "removed_columns": [],
            "removed_joins": [],
            "removed_filters": [],
            "changed_rules": [],
        }

    # ── column names ────────────────────────────────────────────────────────
    current_columns = set(mapping.get("target_columns", {}).keys())
    snap_columns    = set(snapshot.get("target_columns", []))

    new_columns     = sorted(current_columns - snap_columns)
    removed_columns = sorted(snap_columns - current_columns)

    # ── transformation rule changes (name unchanged but rule text differs) ──
    current_col_rules = set(
        f"{k}={v}" for k, v in mapping.get("target_columns", {}).items()
    )
    snap_col_rules = set(snapshot.get("column_rules", []))

    # rules present in current but not in snapshot (new or changed)
    added_rules   = current_col_rules - snap_col_rules
    # rules present in snapshot but not in current (removed or changed)
    removed_rules = snap_col_rules    - current_col_rules

    # A rule is "changed" when the column name exists in both versions but the
    # rule text has changed (i.e. it appears in both added_rules and removed_rules
    # under the same column name prefix).
    added_rule_cols   = {r.split("=", 1)[0] for r in added_rules}
    removed_rule_cols = {r.split("=", 1)[0] for r in removed_rules}
    changed_rules = sorted(
        added_rule_cols & removed_rule_cols & (current_columns & snap_columns)
    )

    # ── joins ────────────────────────────────────────────────────────────────
    current_joins = set(str(j.get("keys", [])) for j in mapping.get("joins", []))
    snap_joins    = set(snapshot.get("joins", []))
    new_joins     = sorted(current_joins - snap_joins)
    removed_joins = sorted(snap_joins    - current_joins)

    # ── filters / conditions ─────────────────────────────────────────────────
    current_filters = set(str(f).strip() for f in mapping.get("filters", []))
    snap_filters    = set(snapshot.get("filters", []))
    new_filters     = sorted(current_filters - snap_filters)
    removed_filters = sorted(snap_filters    - current_filters)

    has_changes = bool(
        new_columns or removed_columns or changed_rules
        or new_joins or removed_joins
        or new_filters or removed_filters
    )

    return {
        "has_changes": has_changes,
        "is_first_run": False,
        "new_columns": new_columns,
        "removed_columns": removed_columns,
        "changed_rules": changed_rules,      # ← NEW: columns with changed transformation logic
        "new_joins": new_joins,
        "removed_joins": removed_joins,
        "new_filters": new_filters,
        "removed_filters": removed_filters,
    }