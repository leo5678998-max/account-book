# Backward compatibility wrapper: forwards to app.core.database
from .core.database import (
    BASE_DIR,
    DEFAULT_DB_PATH,
    default_sqlite_url,
    DATABASE_URL,
    engine,
    SessionLocal,
    Base,
    get_db,
)

__all__ = [
    "BASE_DIR",
    "DEFAULT_DB_PATH",
    "default_sqlite_url",
    "DATABASE_URL",
    "engine",
    "SessionLocal",
    "Base",
    "get_db",
]
