import logging
from kuzu import Connection, Database
from app.core.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def delete_all_documents():
    """Deletes all Document nodes and their related nodes/relationships from KùzuDB."""
    try:
        # Connect to the KùzuDB database
        db = Database(settings.KUZUDB_PATH)
        conn = Connection(db)
        logger.info(f"Connected to KùzuDB at {settings.KUZUDB_PATH}")

        # Delete all Document nodes and their related nodes/relationships
        query = """
        MATCH (d:Document)
        OPTIONAL MATCH (d)-[:Contains]->(c:Chunk)
        DETACH DELETE d, c
        """
        conn.execute(query)
        logger.info("Successfully deleted all Document nodes and related data.")

    except Exception as e:
        logger.error(f"Error deleting documents: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    delete_all_documents()