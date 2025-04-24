from kuzu import Database as KuzuDB, Connection
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants for schema (nodes and relationships)
DOCUMENT_TABLE = "Document"
CHUNK_TABLE = "Chunk"
REQUIREMENT_TABLE = "Requirement"
ENTITY_TABLE = "Entity"

CONTAINS_RELATIONSHIP = "Contains"
DESCRIBED_BY_RELATIONSHIP = "DescribedBy"
REFERENCES_RELATIONSHIP = "References"
IMPLEMENTS_RELATIONSHIP = "Implements"

def get_db():
    """FastAPI dependency that yields a KuzuDBClient (with .execute())."""
    client = KuzuDBClient("/data/kuzu_db")
    try:
        client.connect()
        yield client
    finally:
        client.close()

# Maintain backward compatibility
get_db_connection = get_db

def close_db_connection():
    """Close database connection (no-op for per-request dependency)."""
    pass

class KuzuDBClient:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.kuzu_db: KuzuDB | None = None
        self.conn: Connection | None = None

    def connect(self):
        """Connect to the KuzuDB database and ensure core tables exist."""
        if not self.kuzu_db:
            self.kuzu_db = KuzuDB(self.db_path)
            self.conn = Connection(self.kuzu_db)
            # Ensure core tables exist on connect
            try:
                # Node tables
                self.conn.execute(f"""
                    CREATE NODE TABLE IF NOT EXISTS {DOCUMENT_TABLE} (
                        doc_id STRING,
                        filename STRING,
                        processed_at STRING,
                        status STRING,
                        created_at STRING,
                        updated_at STRING,
                        error STRING,
                        PRIMARY KEY (doc_id)
                    )
                """)
                
                self.conn.execute(f"""
                    CREATE NODE TABLE IF NOT EXISTS {CHUNK_TABLE} (
                        chunk_id STRING,
                        doc_id STRING,
                        text STRING,
                        embedding FLOAT[],
                        created_at STRING,
                        PRIMARY KEY (chunk_id)
                    )
                """)
                
                self.conn.execute(f"""
                    CREATE NODE TABLE IF NOT EXISTS {REQUIREMENT_TABLE} (
                        req_id STRING,
                        type STRING,
                        description STRING,
                        created_at STRING,
                        PRIMARY KEY (req_id)
                    )
                """)
                
                self.conn.execute(f"""
                    CREATE NODE TABLE IF NOT EXISTS {ENTITY_TABLE} (
                        entity_id STRING,
                        type STRING,
                        name STRING,
                        PRIMARY KEY (entity_id)
                    )
                """)

                # Relationship tables
                self.conn.execute(f"""
                    CREATE REL TABLE IF NOT EXISTS {CONTAINS_RELATIONSHIP} (
                        FROM {DOCUMENT_TABLE} TO {CHUNK_TABLE}
                    )
                """)
                
                self.conn.execute(f"""
                    CREATE REL TABLE IF NOT EXISTS {DESCRIBED_BY_RELATIONSHIP} (
                        FROM {REQUIREMENT_TABLE} TO {CHUNK_TABLE}
                    )
                """)
                
                self.conn.execute(f"""
                    CREATE REL TABLE IF NOT EXISTS {REFERENCES_RELATIONSHIP} (
                        FROM {REQUIREMENT_TABLE} TO {DOCUMENT_TABLE}
                    )
                """)
                
                self.conn.execute(f"""
                    CREATE REL TABLE IF NOT EXISTS {IMPLEMENTS_RELATIONSHIP} (
                        FROM {REQUIREMENT_TABLE} TO {ENTITY_TABLE}
                    )
                """)
                
                logger.info("KùzuDB schema initialized successfully.")

            except Exception as e:
                logger.error(f"Error ensuring core tables exist: {e}")
                raise

    def close(self):
        """Close the connection (and drop DB handle)."""
        if self.conn:
            self.conn.close()
            self.conn = None
        self.kuzu_db = None

    def execute(self, query: str, params: dict | None = None):
        """Run a query via the Connection."""
        if not self.conn:
            self.connect()
        if params is not None:
            return self.conn.execute(query, params)
        return self.conn.execute(query)