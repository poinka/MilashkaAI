import logging
import os
from datetime import datetime
from kuzu import Database, Connection
from app.core.models import get_embedding_pipeline
from app.core.config import settings

# Constants for schema
DOCUMENT_TABLE = "Document"
CHUNK_TABLE = "Chunk"
CONTAINS_RELATIONSHIP = "Contains"

# Global database connection
kuzu_db = None
kuzu_conn = None

def get_db_connection() -> Connection:
    """Returns a KuzuDB Connection object, reusing existing connection if available."""
    global kuzu_db, kuzu_conn
    
    if kuzu_conn is not None:
        return kuzu_conn
        
    try:
        # Use the path defined in settings
        db_path = settings.KUZUDB_PATH
        os.makedirs(db_path, exist_ok=True)
        
        logging.info(f"Connecting to KuzuDB at: {db_path}")
        kuzu_db = Database(db_path)
        kuzu_conn = Connection(kuzu_db)
        return kuzu_conn
    except Exception as e:
        logging.error(f"Failed to establish KuzuDB connection: {e}")
        raise


def close_db_connection():
    """Close KuzuDB connection."""
    global kuzu_db, kuzu_conn
    if kuzu_conn:
        kuzu_conn = None
    if kuzu_db:
        kuzu_db = None
        logging.info("KuzuDB connection closed")