import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


def load_preferences(db_path: Path) -> dict:
    """Load user preferences from preferences.yaml next to the database.

    Returns an empty dict if the file does not exist or cannot be parsed.
    """
    yaml_path = db_path.with_name("preferences.yaml")
    if not yaml_path.exists():
        return {}
    try:
        data = yaml.safe_load(yaml_path.read_text())
        if not isinstance(data, dict):
            log.warning("preferences.yaml: expected a dict, got %s", type(data).__name__)
            return {}
        return data
    except Exception:
        log.warning("Failed to parse %s", yaml_path, exc_info=True)
        return {}


def save_preferences(db_path: Path, prefs: dict) -> None:
    """Write user preferences to preferences.yaml next to the database."""
    yaml_path = db_path.with_name("preferences.yaml")
    try:
        yaml_path.write_text(yaml.safe_dump(prefs, default_flow_style=False))
    except Exception:
        log.warning("Failed to write %s", yaml_path, exc_info=True)
