"""Central paths for every component. Import paths from here; never hard-code them.

Layout under the project root:
    config/resorts.yaml   resorts and their points
    data/bronze/          raw API responses (written by pipelines/ingestion)
    data/warehouse/       Iceberg tables (written by pipelines/transformation)
"""
import os
from pathlib import Path


def _find_project_root() -> Path:
    """Return the folder that holds `config/resorts.yaml`.

    1. If the `SKIIPREP_HOME` environment variable is set, use it. Tests and
       deployments (e.g. a container) set it to say where the project lives.
    2. Otherwise walk up from the current directory until a folder contains
       `config/resorts.yaml`. This works from the repo root or any subfolder.

    We don't use `Path(__file__).parents[n]`: that breaks whenever the
    package moves or is installed outside the repo.
    """
    if home := os.environ.get("SKIIPREP_HOME"):
        return Path(home)
    for folder in [Path.cwd(), *Path.cwd().parents]:
        if (folder / "config" / "resorts.yaml").exists():
            return folder
    raise RuntimeError("Can't find the project root; set SKIIPREP_HOME")


# Resolved once, when this module is first imported.
PROJECT_ROOT = _find_project_root()

DATA_DIR = PROJECT_ROOT / "data"  # git-ignored; rebuilt by the pipelines
DATA_BRONZE_DIR = DATA_DIR / "bronze"
DATA_WAREHOUSE_DIR = DATA_DIR / "warehouse"

CONFIG_DIR = PROJECT_ROOT / "config"
RESORTS_FILE = CONFIG_DIR / "resorts.yaml"
