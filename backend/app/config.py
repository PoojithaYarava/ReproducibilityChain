import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
storage_path = Path(os.getenv("ARTIFACT_STORAGE_DIR", "storage"))
STORAGE_ROOT = (
    storage_path if storage_path.is_absolute() else PROJECT_ROOT / storage_path
).resolve()
DATABASE_URL = os.getenv(
    "DATABASE_URL", f"sqlite:///{PROJECT_ROOT / 'reproducibility_chain.db'}"
)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.removeprefix("postgres://")
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.removeprefix("postgresql://")
JWT_SECRET = os.getenv("JWT_SECRET") or secrets.token_urlsafe(48)
if os.getenv("APP_ENV") == "production" and not os.getenv("JWT_SECRET"):
    raise RuntimeError("JWT_SECRET must be set in production")
JWT_LIFETIME_SECONDS = int(os.getenv("JWT_LIFETIME_SECONDS", "3600"))
MAX_ARTIFACT_BYTES = int(os.getenv("MAX_ARTIFACT_BYTES", str(100 * 1024 * 1024)))
BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
BOOTSTRAP_ADMIN_TOKEN = os.getenv("BOOTSTRAP_ADMIN_TOKEN", "")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173,"
        "http://127.0.0.1:5174,http://localhost:5174",
    ).split(",")
    if origin.strip()
]
