"""Central configuration. Change models and limits here, not scattered through the code."""
from pathlib import Path
import os

def _find_project_root() -> Path:
    if home := os.environ.get("SKIIPREP_HOME"):
        return Path(home)
    for folder in [Path.cwd(), *Path.cwd().parents]:
        if (folder / "config" / "resorts.yaml").exists():
            return folder
    raise RuntimeError("Can't find the project root; set SKIIPREP_HOME")

PROJECT_ROOT = _find_project_root()
DATA_DIR = PROJECT_ROOT / "data"

DATA_BRONZE_DIR = DATA_DIR / "bronze"
DATA_WAREHOUSE_DIR = DATA_DIR / "warehouse"

CONFIG_DIR = PROJECT_ROOT / "config"
RESORTS_FILE = CONFIG_DIR / "resorts.yaml"