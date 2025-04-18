from kuzu import Database
from app.core.config import settings
import logging

kuzu_db: Database | None = None

def get_db_connection() -> Database:
    """Get or create KuzuDB connection."""
    global kuzu_db
    if kuzu_db is None:
        try:
            kuzu_db = Database(settings.KUZUDB_PATH)
            logging.info("KuzuDB connection established")
        except Exception as e:
            logging.error(f"Error connecting to KuzuDB: {e}")
            raise
    return kuzu_db

def close_db_connection():
    """Close KuzuDB connection."""
    global kuzu_db
    if kuzu_db:
        kuzu_db = None
        logging.info("KuzuDB connection closed")