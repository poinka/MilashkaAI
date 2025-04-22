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
        db.execute(f"""
    CREATE NODE TABLE IF NOT EXISTS {CHUNK_TABLE} (
        chunk_id STRING,
        doc_id STRING,
        text STRING,
        embedding FLOAT[{settings.VECTOR_DIMENSION}],
        created_at STRING,
        PRIMARY KEY (chunk_id)
    )
""")
        
        # Generate query embedding
        query_vector = embedding_pipeline.encode([query_text])[0]

        # Build query based on whether we have a doc_id filter
        if filter_doc_id:
            results = db.execute("""
                MATCH (c:Chunk)
                WHERE c.doc_id = $doc_id
                WITH c, vector_cosine_similarity(c.embedding, $embedding) as score
                ORDER BY score DESC
                LIMIT $top_k
                RETURN c.chunk_id, c.text, c.doc_id, score
            """, {
                "doc_id": filter_doc_id,
                "embedding": query_vector.tolist(),
                "top_k": top_k
            })
        else:
            results = db.execute("""
                MATCH (c:Chunk)
                WITH c, vector_cosine_similarity(c.embedding, $embedding) as score
                ORDER BY score DESC
                LIMIT $top_k
                RETURN c.chunk_id, c.text, c.doc_id, score
            """, {
                "embedding": query_vector.tolist(),
                "top_k": top_k
            })
        
        chunks = []
        while results.has_next():
            row = results.get_next()
            chunks.append({
                "text": row[1],
                "score": float(row[3]),
                "metadata": {
                    "doc_id": row[2],
                    "chunk_id": row[0]
                }
            })
        
        # Add detailed logging for chunks
        if chunks:
            logging.info(f"📚 Retrieved {len(chunks)} chunks with scores:")
            for i, chunk in enumerate(chunks):
                # Truncate text to avoid excessively long logs
                preview = chunk["text"][:150] + "..." if len(chunk["text"]) > 150 else chunk["text"]
                logging.info(f"Chunk {i+1} (Score: {chunk['score']:.4f}): \"{preview}\"")
        else:
            logging.info("No chunks found matching the query")
        
        return chunks

    except Exception as e:
        logger.error(f"Error retrieving chunks: {e}", exc_info=True)
        return []