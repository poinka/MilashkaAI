import logging
from datetime import datetime
from kuzu import Database, Connection
from app.core.models import get_embedding_pipeline
from app.core.config import settings

# Constants for schema
DOCUMENT_TABLE = "Document"
CHUNK_TABLE = "Chunk"
CONTAINS_RELATIONSHIP = "Contains"

def get_db_connection() -> Connection:
    """Returns a KuzuDB Connection object."""
    try:
        # Adjust the path to your database storage location
        database = Database("/app/data/kuzu_db")  # Example path, update as needed
        conn = Connection(database)
        return conn
    except Exception as e:
        logging.error(f"Failed to establish KuzuDB connection: {e}")
        raise


def close_db_connection():
    """Close KuzuDB connection."""
    global kuzu_db
    if kuzu_db:
        kuzu_db = None
        logging.info("KuzuDB connection closed")