"""Runtime configuration. Provider secrets are read here and never returned by the API."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Uvicorn runs with cwd=backend, so a relative ".env" never sees the project file.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    framefit_mode: str = "demo"
    secret_key: str = "dev-only-change-me"
    database_url: str = "sqlite:///./data/framefit.db"
    storage_backend: str = "local"
    local_storage_dir: str = "./data/assets"
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "auto"
    s3_public_base_url: str = ""
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    public_base_url: str = ""

    youcam_api_key: str = ""
    youcam_base_url: str = "https://yce-api-01.makeupar.com"
    youcam_input_mode: str = "file_upload"
    youcam_reference_kind: str = "crop"
    youcam_timeout_seconds: float = 180
    youcam_poll_interval_seconds: float = 2

    serpapi_api_key: str = ""
    serpapi_base_url: str = "https://serpapi.com"

    yolo_model: str = "yolov8s-worldv2.pt"
    yolo_device: str = "cpu"
    yolo_confidence: float = 0.15
    yolo_image_size: int = 640
    yolo_concurrency: int = 1
    yolo_cache_dir: str = "./data/models"
    yolo_classes: str = "hat,scarf,jacket,coat,shirt,sweater,trousers,skirt,dress,shoe,bag"

    max_upload_bytes: int = 12_000_000
    max_image_edge: int = 8000
    max_generations_per_session: int = 40
    max_storage_bytes: int = 524_288_000
    max_job_concurrency: int = 2
    rate_limit_per_minute: int = 120
    framefit_worker: int = 1
    port: int = 8000

    @property
    def mode(self) -> str:
        value = self.framefit_mode.strip().lower()
        if value not in {"demo", "mixed", "real"}:
            return "demo"
        return value

    @property
    def origins(self) -> list[str]:
        return [item.strip() for item in self.frontend_origins.split(",") if item.strip()]

    @property
    def class_prompts(self) -> list[str]:
        return [item.strip().lower() for item in self.yolo_classes.split(",") if item.strip()]

    @property
    def youcam_configured(self) -> bool:
        return bool(self.youcam_api_key.strip())

    @property
    def serpapi_configured(self) -> bool:
        return bool(self.serpapi_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    Path(settings.local_storage_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.yolo_cache_dir).mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite:///"):
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        if db_path != ":memory:" and not db_path.startswith("file:"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return settings
