from typing import List, Dict, Any
import numpy as np
import logging
from app.db.kuzudb_client import get_db, KuzuDBClient
from fastapi import Depends
from app.core.models import get_embedding_pipeline
from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Constants for schema
DOCUMENT_TABLE = "Document"
CHUNK_TABLE = "Chunk"

async def retrieve_relevant_chunks(
    query_text: str,
    embedding_pipeline,
    db: KuzuDBClient = None,
    filter_doc_id=None,
    top_k=3
) -> List[Dict]:
    # Check if input contains non-ASCII characters
    if not all(ord(c) < 128 for c in query_text):
        logger.warning("Non-ASCII text detected, skipping vector search")
        # ensure db
        close_db = False
        if db is None:
            db = KuzuDBClient(settings.KUZUDB_PATH)
            db.connect()
            close_db = True
        try:
            # Use a simple text-based fallback query
            if filter_doc_id:
                results = db.execute(
                    "MATCH (c:Chunk) WHERE c.doc_id = $doc_id RETURN c.chunk_id, c.text, c.doc_id, 1.0 as score LIMIT $top_k", {"doc_id": filter_doc_id, "top_k": top_k}
                )
            else:
                results = db.execute(
                    "MATCH (c:Chunk) RETURN c.chunk_id, c.text, c.doc_id, 1.0 as score LIMIT $top_k", {"top_k": top_k}
                )
        except Exception as e:
            logger.error(f"Error in fallback query: {e}")
            return []
        finally:
            if close_db:
                db.close()
    else:
        # Original vector search code for ASCII text
        close_db = False
        if db is None:
            db = KuzuDBClient(settings.KUZUDB_PATH)
            db.connect()
            close_db = True
        # Ensure necessary tables exist
        db.execute(f"""
            CREATE NODE TABLE IF NOT EXISTS {DOCUMENT_TABLE} (
                doc_id STRING PRIMARY KEY,
                filename STRING,
                status STRING,
                created_at STRING,
                updated_at STRING,
                processed_at STRING,
                error STRING
            )
        """
        )
        db.execute(f"""
            CREATE NODE TABLE IF NOT EXISTS {CHUNK_TABLE} (
                chunk_id STRING PRIMARY KEY,
                doc_id STRING,
                text STRING,
                embedding FLOAT[]
            )
        """
        )
        try:
            embedding_pipeline = get_embedding_pipeline()

            # Generate query embedding
            query_vector = embedding_pipeline.encode([query_text])[0]

            # Convert numpy array to list and ensure it's finite
            query_vector_list = [float(x) for x in query_vector.tolist()]
            if not all(map(lambda x: -1e6 < x < 1e6, query_vector_list)):
                logger.warning("Query vector contains extreme values, normalizing...")
                max_abs = max(map(abs, query_vector_list))
                if max_abs > 0:
                    query_vector_list = [x/max_abs for x in query_vector_list]

            # Build query based on whether we have a doc_id filter
            if filter_doc_id:
                results = db.execute("""
                    MATCH (c:Chunk)
                    WHERE c.doc_id = $doc_id
                    RETURN c.chunk_id, c.text, c.doc_id, 1.0 as score
                    LIMIT $top_k
                """, {
                    "doc_id": filter_doc_id,
                    "top_k": top_k
                })
            else:
                results = db.execute("""
                    MATCH (c:Chunk)
                    RETURN c.chunk_id, c.text, c.doc_id, 1.0 as score
                    LIMIT $top_k
                """, {
                    "top_k": top_k
                })
        except Exception as e:
            logger.error(f"Error in vector search: {e}")
            return []
        finally:
            if close_db:
                db.close()
    chunks = []
    try:
        while results and results.has_next():
            row = results.get_next()
            chunks.append({
                "text": row[1],
                "score": float(row[3]),
                "metadata": {
                    "doc_id": row[2],
                    "chunk_id": row[0]
                }
            })
    except Exception as e:
        logger.error(f"Error processing results: {e}")
        return []

    return chunks