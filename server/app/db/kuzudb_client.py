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
        """Connect to the KuzuDB database."""
        if not self.kuzu_db:
            self.kuzu_db = KuzuDB(self.db_path)
            self.conn = Connection(self.kuzu_db)

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