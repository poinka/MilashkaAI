from kuzu import Database as KuzuDB, Connection

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
                self.conn.execute("""
                    CREATE NODE TABLE IF NOT EXISTS Document (
                        doc_id STRING PRIMARY KEY,
                        filename STRING,
                        status STRING,
                        created_at STRING,
                        updated_at STRING,
                        processed_at STRING,
                        error STRING
                    )
                """)
                self.conn.execute("""
                    CREATE NODE TABLE IF NOT EXISTS Chunk (
                        chunk_id STRING PRIMARY KEY,
                        doc_id STRING,
                        text STRING,
                        embedding FLOAT[]
                    )
                """)
                self.conn.execute("""
                    CREATE REL TABLE IF NOT EXISTS Contains (
                        FROM Document TO Chunk
                    )
                """)
            except Exception as e:
                # Log this error appropriately in a real application
                print(f"Error ensuring core tables exist: {e}")
                # Depending on the severity, you might want to raise the exception
                # raise

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