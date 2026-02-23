import logging
import sys

from pyre.db import DB_PATH, release_lock
from pyre.ui.app import PyreApp

if __name__ == "__main__":
    log_path = DB_PATH.with_suffix(".log")
    logging.basicConfig(
        filename=log_path,
        level=logging.ERROR,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    import_file = sys.argv[1] if len(sys.argv) > 1 else None
    app = PyreApp(import_file=import_file)
    try:
        app.run()
    finally:
        release_lock()
