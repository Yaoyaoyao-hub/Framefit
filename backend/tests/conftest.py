import os
import tempfile
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix="framefit-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_root / 'test.db'}"
os.environ["LOCAL_STORAGE_DIR"] = str(_root / "assets")
os.environ["YOLO_CACHE_DIR"] = str(_root / "models")
os.environ["FRAMEFIT_MODE"] = "demo"
os.environ["FRAMEFIT_WORKER"] = "0"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["RATE_LIMIT_PER_MINUTE"] = "10000"
os.environ["YOUCAM_API_KEY"] = ""
os.environ["SERPAPI_API_KEY"] = ""

from app.config import get_settings

get_settings.cache_clear()

from app.db import init_db, reset_engine
from app.storage import reset_storage

reset_engine()
reset_storage()
init_db()
