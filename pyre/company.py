import logging
from pathlib import Path

import yaml

from pyre.db import DB_PATH

log = logging.getLogger(__name__)


def load_company_config(db_path: Path) -> dict:
    """Load company configuration from company.yaml next to the database."""
    yaml_path = db_path.with_name("company.yaml")
    if not yaml_path.exists():
        return {}
    try:
        data = yaml.safe_load(yaml_path.read_text())
        if not isinstance(data, dict):
            log.warning("company.yaml: expected a dict, got %s", type(data).__name__)
            return {}
        return data
    except Exception:
        log.warning("Failed to parse %s", yaml_path, exc_info=True)
        return {}


COMPANY_NAME = load_company_config(DB_PATH).get("name", "")
