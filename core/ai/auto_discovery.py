# core/ai/auto_discovery.py
"""
Smart auto-discovery of data files in the project.
Scans known directories for mapping documents, profiled CSVs,
raw data, reference tables, sample data, and scenario JSON files.
"""

from pathlib import Path
from typing import Dict, List, Optional
import os
from core.storage.blob_storage import list_files
USE_BLOB_STORAGE = True


def _project_root() -> Path:
    """Return project root (two levels up from this file)."""
    return Path(__file__).resolve().parents[2]


def discover_mapping_files(data_dir: Optional[Path] = None) -> List:

    if USE_BLOB_STORAGE:

        files = list_files("mapping/")

        return [
            {
                "name": f.split("/")[-1],
                "path": f
            }
            for f in files if f.endswith(".xlsx")
        ]

    else:

        data_dir = data_dir or _project_root() / "data"

        mapping_dir = data_dir / "mapping_document"

        if not mapping_dir.exists():
            return []

        return sorted(mapping_dir.glob("*.xlsx"))
    


def discover_profiled_files(data_dir: Optional[Path] = None) -> Dict:

    if USE_BLOB_STORAGE:

        files = list_files("profiled/")

        result = {}

        for f in files:

            filename = f.split("/")[-1]

            if filename.endswith("_profiled.csv"):

                table_name = filename.replace("_profiled.csv", "")

                result[table_name.upper()] = f

        return result

    else:

        data_dir = data_dir or _project_root() / "data"

        profiled_dir = data_dir / "profiled"

        if not profiled_dir.exists():
            return {}

        result = {}

        for f in profiled_dir.glob("*_profiled.csv"):

            table_name = f.stem.replace("_profiled", "")

            result[table_name] = f

        return result
    


def discover_raw_files(data_dir: Optional[Path] = None) -> Dict:

    if USE_BLOB_STORAGE:

        files = list_files("raw/")

        result = {}

        for f in files:

            filename = f.split("/")[-1]

            if filename.endswith(".csv"):

                table_name = filename.replace(".csv", "").upper()

                result[table_name] = f

        return result

    else:

        data_dir = data_dir or _project_root() / "data"

        raw_dir = data_dir / "raw"

        if not raw_dir.exists():
            return {}

        result = {}

        for f in raw_dir.rglob("*.csv"):

            if ".ipynb_checkpoints" in str(f):
                continue

            table_name = f.stem.upper()

            result[table_name] = f

        return result


def discover_sample_files(data_dir: Optional[Path] = None) -> Dict:

    if USE_BLOB_STORAGE:

        files = list_files("sample/")

        result = {}

        for f in files:

            filename = f.split("/")[-1]

            if filename.endswith(".csv"):

                table_name = filename.replace("_sample.csv", "").upper()

                result[table_name] = f

        return result

    else:

        data_dir = data_dir or _project_root() / "data"

        sample_dir = data_dir / "sample"

        if not sample_dir.exists():
            return {}

        result = {}

        for f in sample_dir.glob("*.csv"):

            table_name = f.stem.replace("_sample", "").upper()

            result[table_name] = f

        return result


def discover_scenario_dirs(data_dir: Optional[Path] = None) -> Dict[str, Path]:
    """
    Find existing scenario directories.
    Returns {TARGET_TABLE: Path} e.g. {"TARGET_FACTS": Path(...)}
    """
    data_dir = data_dir or _project_root() / "data"
    scenarios_dir = data_dir / "scenarios"
    if not scenarios_dir.exists():
        return {}

    result = {}
    for d in scenarios_dir.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            # Count JSON files to confirm it's a valid scenario dir
            json_count = len(list(d.rglob("*.json")))
            if json_count > 0:
                result[d.name] = d
    return result


def find_best_source_file(
    table_name: str,
    data_dir: Optional[Path] = None
) -> Optional[Dict]:
    """
    For a given source table, find the best available file.
    Priority:
      1. Profiled file (data/profiled/{TABLE}_profiled.csv)
      2. Raw file (data/raw/**/{TABLE}.csv)
      3. Sample file (data/sample/{TABLE}_sample.csv or {TABLE}.csv)
      4. None — user must upload

    Returns dict with keys: path, source_type, table_name
    """
    data_dir = data_dir or _project_root() / "data"
    table_upper = table_name.upper()

    # 1. Check profiled
    profiled = discover_profiled_files(data_dir)
    if table_upper in profiled:
        return {
            "path": profiled[table_upper],
            "source_type": "profiled",
            "table_name": table_upper,
        }

    # 2. Check raw
    raw = discover_raw_files(data_dir)
    if table_upper in raw:
        return {
            "path": raw[table_upper],
            "source_type": "raw",
            "table_name": table_upper,
        }

    # 3. Check sample
    sample = discover_sample_files(data_dir)
    if table_upper in sample:
        return {
            "path": sample[table_upper],
            "source_type": "sample",
            "table_name": table_upper,
        }

    return None


def discover_all(data_dir: Optional[Path] = None) -> Dict:
    """
    Full inventory of all discovered data assets.
    """
    data_dir = data_dir or _project_root() / "data"
    return {
        "mapping_files": discover_mapping_files(data_dir),
        "profiled_files": discover_profiled_files(data_dir),
        "raw_files": discover_raw_files(data_dir),
        "sample_files": discover_sample_files(data_dir),
        "scenario_dirs": discover_scenario_dirs(data_dir),
    }
