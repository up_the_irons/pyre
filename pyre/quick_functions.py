import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


def load_quick_functions(db_path: Path) -> list[dict]:
    """Load quick functions from a YAML file next to the database.

    Returns an empty list if the file does not exist or cannot be parsed.
    """
    yaml_path = db_path.with_name("quick_functions.yaml")
    if not yaml_path.exists():
        return []
    try:
        data = yaml.safe_load(yaml_path.read_text())
        if not isinstance(data, list):
            log.warning("quick_functions.yaml: expected a list, got %s", type(data).__name__)
            return []
        return data
    except Exception:
        log.warning("Failed to parse %s", yaml_path, exc_info=True)
        return []
