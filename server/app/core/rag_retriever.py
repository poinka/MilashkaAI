from typing import List, Dict, Any
import numpy as np
import logging
from app.db.kuzudb_client import get_db_connection
from app.core.models import get_embedding_pipeline
from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Constant for schema
CHUNK_TABLE = "Chunk"

async def retrieve_relevant_chunks(
    query_text: str,
    top_k: int,
    filter_doc_id: str | None = None
) -> List[Dict[str, Any]]:
    """Retrieves relevant chunks using KuzuDB."""
    try:
        db = get_db_connection()
        embedding_pipeline = get_embedding_pipeline()
        
        # Ensure the Chunk table exists with the correct schema
        logger.debug("Ensuring Chunk table exists with embedding array")
        db.execute("""
    CREATE NODE TABLE IF NOT EXISTS Chunk (
        chunk_id STRING,
        doc_id STRING,
        text STRING,
        embedding FLOAT[768],
        created_at STRING,
        PRIMARY KEY (chunk_id)
    )
""")
        
        # Generate query embedding
        query_vector = embedding_pipeline.encode([query_text])[0]
        query_vector = query_vector / np.linalg.norm(query_vector)  # Normalize the query vector
        
        # Fetch all chunks (with optional doc_id filter)
        if filter_doc_id:
            query = """
            MATCH (c:Chunk)
            WHERE c.doc_id = $doc_id
            RETURN c.chunk_id, c.text, c.doc_id, c.embedding
            """
            params = {"doc_id": filter_doc_id}
        else:
            query = """
            MATCH (c:Chunk)
            RETURN c.chunk_id, c.text, c.doc_id, c.embedding
            """
            params = {}

        logger.debug(f"Executing query: {query}")
        logger.debug(f"With parameters: {params}")

        result = db.execute(query, params)
        chunks = []
        while result.has_next():
            row = result.get_next()
            chunks.append({
                "chunk_id": row[0],
                "text": row[1],
                "doc_id": row[2],
                "embedding": np.array(row[3])
            })

        # Compute cosine similarity in Python
        scored_chunks = []
        for chunk in chunks:
            chunk_embedding = chunk["embedding"]
            if chunk_embedding is None or len(chunk_embedding) != len(query_vector):
                logger.warning(f"Invalid embedding for chunk {chunk['chunk_id']}, skipping")
                continue
            chunk_embedding = chunk_embedding / np.linalg.norm(chunk_embedding)  # Normalize
            score = float(np.dot(query_vector, chunk_embedding))  # Cosine similarity
            scored_chunks.append({
                "text": chunk["text"],
                "score": score,
                "metadata": {
                    "doc_id": chunk["doc_id"],
                    "chunk_id": chunk["chunk_id"]
                }
            })

        # Sort by score and take top_k
        scored_chunks.sort(key=lambda x: x["score"], reverse=True)
        return scored_chunks[:top_k]

    except Exception as e:
        logger.error(f"Error retrieving chunks: {e}", exc_info=True)
        return []