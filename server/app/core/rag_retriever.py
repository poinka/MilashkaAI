from typing import List, Dict, Any
import numpy as np
from app.db.kuzudb_client import get_db_connection
from app.core.models import get_embedding_pipeline
from app.core.config import settings

async def retrieve_relevant_chunks(
    query_text: str,
    top_k: int,
    filter_doc_id: str | None = None
) -> List[Dict[str, Any]]:
    """Retrieves relevant chunks using KuzuDB vector similarity."""
    try:
        db = get_db_connection()
        embedding_pipeline = get_embedding_pipeline()
        
        # Generate query embedding
        query_vector = embedding_pipeline.encode([query_text])[0]

        # Build query with vector similarity and optional doc filter
        filter_clause = f"AND c.doc_id = '{filter_doc_id}'" if filter_doc_id else ""
        
        query = f"""
        MATCH (c:{CHUNK_TABLE})
        WHERE true {filter_clause}
        WITH c, vector_cosine_similarity(c.embedding, $1) as score
        ORDER BY score DESC
        LIMIT {top_k}
        RETURN c.chunk_id, c.text, c.doc_id, score
        """

        results = db.query(query, [query_vector.tolist()])
        
        return [{
            "text": row[1],
            "score": float(row[3]),
            "metadata": {
                "doc_id": row[2],
                "chunk_id": row[0]
            }
        } for row in results]

    except Exception as e:
        logging.error(f"Error retrieving chunks: {e}")
        return []