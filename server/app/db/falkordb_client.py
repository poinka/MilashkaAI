import redis
from falkordb import FalkorDB
from app.core.config import settings

# Global variable to hold the database connection
# In a production scenario, consider connection pooling or dependency injection
falkor_db_client: FalkorDB | None = None

def get_db_connection() -> FalkorDB:
    """Establishes or returns the existing FalkorDB connection."""
    global falkor_db_client
    if falkor_db_client is None:
        try:
            # FalkorDB uses the Redis client for connection
            r = redis.Redis(
                host=settings.FALKORDB_HOST,
                port=settings.FALKORDB_PORT,
                password=settings.FALKORDB_PASSWORD,
                decode_responses=True # Important for handling strings
            )
            r.ping() # Check connection
            falkor_db_client = FalkorDB(r)
            print(f"Successfully connected to FalkorDB at {settings.FALKORDB_HOST}:{settings.FALKORDB_PORT}")
        except redis.exceptions.ConnectionError as e:
            print(f"Error connecting to FalkorDB: {e}")
            # Handle connection error appropriately (e.g., raise exception, exit)
            raise ConnectionError(f"Could not connect to FalkorDB: {e}") from e
    return falkor_db_client

def close_db_connection():
    """Closes the FalkorDB connection if it exists."""
    global falkor_db_client
    if falkor_db_client:
        # The underlying redis client connection might need explicit closing depending on the setup
        # For simplicity here, we just reset the global variable.
        # In a real app, ensure resources are properly released.
        try:
            falkor_db_client.connection.close()
            print("FalkorDB connection closed.")
        except Exception as e:
            print(f"Error closing FalkorDB connection: {e}")
        falkor_db_client = None

# Example usage (can be removed later)
# if __name__ == "__main__":
#     try:
#         db = get_db_connection()
#         # Example: Create a graph
#         # graph = db.select_graph('my_graph')
#         # graph.query("CREATE (:Person {name:'Alice'})")
#         # result = graph.query("MATCH (p:Person) RETURN p.name")
#         # print(result.result_set)
#     finally:
#         close_db_connection()
