import logging
from typing import List, Dict, Any
import numpy as np
from app.db.falkordb_client import get_db_connection
from app.core.models import get_embedding_pipeline
from app.core.config import settings
import json
import hashlib
from datetime import datetime, timedelta
import asyncio
from falkordb import FalkorDB

# Import constants defined in rag_builder
from .rag_builder import GLOBAL_INDEX_NAME, VECTOR_FIELD_NAME, CHUNK_LABEL

class RagCache:
    _instance = None
    _cache = {}
    _timestamps = {}

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set(self, key: str, value: Any, ttl: int = None):
        if ttl is None:
            ttl = settings.CACHE_TTL
        self._cache[key] = value
        self._timestamps[key] = datetime.now() + timedelta(seconds=ttl)

    def get(self, key: str) -> Any:
        if key in self._cache:
            if datetime.now() < self._timestamps[key]:
                return self._cache[key]
            else:
                # Expired
                del self._cache[key]
                del self._timestamps[key]
        return None

    def cleanup(self):
        now = datetime.now()
        expired_keys = [k for k, t in self._timestamps.items() if now >= t]
        for k in expired_keys:
            del self._cache[k]
            del self._timestamps[k]

async def retrieve_relevant_chunks(
    query_text: str,
    top_k: int,
    db: FalkorDB,
    filter_doc_id: str | None = None,
    use_cache: bool = True
) -> List[Dict[str, Any]]:
    """
    Retrieves the most relevant text chunks from the indexed documents in FalkorDB
    using vector similarity search with caching support.
    """
    cache = RagCache.get_instance()
    
    # Generate cache key
    cache_key = hashlib.md5(
        f"{query_text}:{top_k}:{filter_doc_id}".encode()
    ).hexdigest()

    # Check cache first
    if use_cache:
        cached_result = cache.get(cache_key)
        if cached_result:
            logging.info("Retrieved chunks from cache")
            return cached_result

    logging.info(f"Retrieving top {top_k} relevant chunks for query: '{query_text[:50]}...'")
    embedding_pipeline = get_embedding_pipeline()

    try:
        # 1. Generate embedding for the query text with batching
        query_embedding = embedding_pipeline.encode(
            [query_text],
            batch_size=settings.BATCH_SIZE,
            show_progress_bar=False
        )[0]
        query_vector_bytes = np.array(query_embedding, dtype=np.float32).tobytes()

        # 2. Construct the search query with optimized parameters
        filter_expression = "*"
        if filter_doc_id:
            safe_doc_id = filter_doc_id.replace('-', '\\\\-')
            filter_expression = f"@doc_id:{{{safe_doc_id}}}"

        # Use pipeline for better performance
        search_query = (
            f"FT.SEARCH {GLOBAL_INDEX_NAME} "
            f"'{filter_expression}=>[KNN {top_k} @{VECTOR_FIELD_NAME} $query_vector AS __v_score]' "
            f"PARAMS 2 query_vector $query_vector_bytes "
            f"RETURN 4 __v_score text doc_id filename "
            f"SORTBY __v_score ASC "
            f"DIALECT 2"
        )

        # 3. Execute search with timeout
        async def execute_with_timeout():
            return await asyncio.wait_for(
                asyncio.to_thread(
                    db.execute_command,
                    search_query,
                    query_vector_bytes
                ),
                timeout=settings.DB_TIMEOUT
            )

        try:
            results = await execute_with_timeout()
        except asyncio.TimeoutError:
            logging.error("Search query timed out")
            return []

        # 4. Process results with similarity threshold
        formatted_chunks = []
        if results and isinstance(results, list) and len(results) > 1:
            num_results = results[0]
            logging.info(f"Found {num_results} potential matches")
            
            for i in range(1, len(results), 2):
                key = results[i]
                fields = results[i+1]
                chunk_data = {}
                
                for j in range(0, len(fields), 2):
                    field_name = fields[j]
                    field_value = fields[j+1]
                    chunk_data[field_name] = field_value

                score = float(chunk_data.get('__v_score', 1.0))
                
                # Apply similarity threshold
                if score <= settings.RAG_SIMILARITY_THRESHOLD:
                    formatted_chunks.append({
                        "text": chunk_data.get("text", ""),
                        "score": score,
                        "metadata": {
                            "doc_id": chunk_data.get("doc_id", "unknown"),
                            "filename": chunk_data.get("filename", "unknown"),
                            "falkordb_key": key
                        }
                    })

        # Sort and limit results
        formatted_chunks.sort(key=lambda x: x['score'])
        final_chunks = formatted_chunks[:top_k]

        # Cache the results
        if use_cache:
            cache.set(cache_key, final_chunks)
            cache.cleanup()  # Cleanup expired entries

        return final_chunks

    except Exception as e:
        logging.error(f"Error retrieving relevant chunks: {e}", exc_info=True)
        return []