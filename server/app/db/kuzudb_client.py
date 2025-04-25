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
ACTOR_TABLE = "Actor"
ACTION_TABLE = "Action"
OBJECT_TABLE = "Object"
RESULT_TABLE = "Result"
PROJECT_ENTITY_TABLE = "ProjectEntity"
USER_INTERACTION_TABLE = "UserInteraction"

CONTAINS_RELATIONSHIP = "Contains"
DESCRIBED_BY_RELATIONSHIP = "DescribedBy"
REFERENCES_RELATIONSHIP = "References"
IMPLEMENTS_RELATIONSHIP = "Implements"
PERFORMS_RELATIONSHIP = "Performs"
COMMITS_RELATIONSHIP = "Commits"
ON_WHAT_PERFORMED_RELATIONSHIP = "On_what_performed"
EXPECTS_RELATIONSHIP = "Expects"
DEPENDS_ON_RELATIONSHIP = "Depends_on"
RELATES_TO_RELATIONSHIP = "Relates_to"
DESCRIBED_IN_RELATIONSHIP = "Described_in"
LINKED_TO_FEEDBACK_RELATIONSHIP = "Linked_to_feedback"

def get_db():
    """FastAPI dependency that yields a KuzuDBClient (with .execute())."""
    from app.core.config import settings
    client = KuzuDBClient(settings.KUZUDB_PATH)
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

            try:
                # Создание схемы
                schema_queries = [
                    f"CREATE NODE TABLE IF NOT EXISTS {ACTOR_TABLE} (id STRING PRIMARY KEY, name STRING, description STRING)",
                    f"CREATE NODE TABLE IF NOT EXISTS {ACTION_TABLE} (id STRING PRIMARY KEY, name STRING, description STRING)",
                    f"CREATE NODE TABLE IF NOT EXISTS {OBJECT_TABLE} (id STRING PRIMARY KEY, name STRING, description STRING)",
                    f"CREATE NODE TABLE IF NOT EXISTS {RESULT_TABLE} (id STRING PRIMARY KEY, description STRING)",
                    f"CREATE NODE TABLE IF NOT EXISTS {PROJECT_ENTITY_TABLE} (id STRING PRIMARY KEY, type STRING, name STRING, description STRING)",
                    f"""
                        CREATE NODE TABLE IF NOT EXISTS {DOCUMENT_TABLE} (
                            doc_id STRING PRIMARY KEY,
                            filename STRING,
                            type STRING,
                            content STRING,
                            status STRING,
                            created_at STRING,
                            updated_at STRING,
                            processed_at STRING
                        )
                        """,           
                    f"CREATE NODE TABLE IF NOT EXISTS {USER_INTERACTION_TABLE} (id STRING PRIMARY KEY, type STRING, suggestion_text STRING, user_reaction STRING, date STRING)",
                    f"CREATE NODE TABLE IF NOT EXISTS {REQUIREMENT_TABLE} (req_id STRING PRIMARY KEY, type STRING, description STRING, created_at STRING)",
                    f"CREATE REL TABLE IF NOT EXISTS {PERFORMS_RELATIONSHIP} (FROM {REQUIREMENT_TABLE} TO {ACTOR_TABLE})",
                    f"CREATE REL TABLE IF NOT EXISTS {COMMITS_RELATIONSHIP} (FROM {REQUIREMENT_TABLE} TO {ACTION_TABLE})",
                    f"CREATE REL TABLE IF NOT EXISTS {ON_WHAT_PERFORMED_RELATIONSHIP} (FROM {REQUIREMENT_TABLE} TO {OBJECT_TABLE})",
                    f"CREATE REL TABLE IF NOT EXISTS {EXPECTS_RELATIONSHIP} (FROM {REQUIREMENT_TABLE} TO {RESULT_TABLE})",
                    f"CREATE REL TABLE IF NOT EXISTS {DEPENDS_ON_RELATIONSHIP} (FROM {REQUIREMENT_TABLE} TO {REQUIREMENT_TABLE})",
                    f"CREATE REL TABLE IF NOT EXISTS {RELATES_TO_RELATIONSHIP} (FROM {REQUIREMENT_TABLE} TO {PROJECT_ENTITY_TABLE})",
                    f"CREATE REL TABLE IF NOT EXISTS {DESCRIBED_IN_RELATIONSHIP} (FROM {REQUIREMENT_TABLE} TO {DOCUMENT_TABLE})",
                    f"CREATE REL TABLE IF NOT EXISTS {LINKED_TO_FEEDBACK_RELATIONSHIP} (FROM {REQUIREMENT_TABLE} TO {USER_INTERACTION_TABLE})",
                    f"CREATE REL TABLE IF NOT EXISTS {CONTAINS_RELATIONSHIP} (FROM {DOCUMENT_TABLE} TO {CHUNK_TABLE})",
                    f"CREATE REL TABLE IF NOT EXISTS {DESCRIBED_BY_RELATIONSHIP} (FROM {REQUIREMENT_TABLE} TO {CHUNK_TABLE})",
                ]
                for query in schema_queries:
                    self.conn.execute(query)

                
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