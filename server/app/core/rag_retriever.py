import logging
from typing import List, Dict, Any
import numpy as np

from app.db.falkordb_client import get_db_connection
from app.core.models import get_embedding_pipeline
from falkordb import FalkorDB

# Import constants defined in rag_builder
from .rag_builder import GLOBAL_INDEX_NAME, VECTOR_FIELD_NAME, CHUNK_LABEL

async def retrieve_relevant_chunks(query_text: str, top_k: int, db: FalkorDB, filter_doc_id: str | None = None) -> List[Dict[str, Any]]:
    """
    Retrieves the most relevant text chunks from the indexed documents in FalkorDB
    using vector similarity search.

    Args:
        query_text: The user's query string.
        top_k: The maximum number of chunks to retrieve.
        db: The FalkorDB connection instance.
        filter_doc_id: Optional document ID to restrict the search to.

    Returns:
        A list of dictionaries, each containing 'text', 'score', and 'metadata'
        (like doc_id, filename) for a relevant chunk.
    """
    logging.info(f"Retrieving top {top_k} relevant chunks for query: '{query_text[:50]}...'")
    embedding_pipeline = get_embedding_pipeline()

    try:
        # 1. Generate embedding for the query text
        query_embedding = embedding_pipeline.encode([query_text])[0]
        query_vector_bytes = np.array(query_embedding, dtype=np.float32).tobytes()

        # 2. Construct the FT.SEARCH query for vector similarity
        # Base query structure for KNN search
        # The filter part needs careful construction based on `filter_doc_id`
        filter_expression = "*" # Default: search all documents in the index
        if filter_doc_id:
            # Escape hyphens or other special characters in doc_id if necessary for TAG fields
            safe_doc_id = filter_doc_id.replace('-', '\\\\-') # Basic escaping for hyphen
            filter_expression = f"@doc_id:{{{safe_doc_id}}}"
            logging.info(f"Applying filter for doc_id: {filter_doc_id}")


        # Construct the FT.SEARCH query
        # Returns the vector score (__v_score), text, doc_id, and filename
        # Ensure field names match the index schema in rag_builder.py
        search_query = (
            f"FT.SEARCH {GLOBAL_INDEX_NAME} "
            f"'{filter_expression}=>[KNN {top_k} @{VECTOR_FIELD_NAME} $query_vector AS __v_score]' "
            f"PARAMS 2 query_vector $query_vector_bytes " # Pass vector as bytes parameter
            f"RETURN 4 __v_score text doc_id filename " # Request score, text, and metadata
            f"SORTBY __v_score ASC " # Lower score (cosine distance) is better
            f"DIALECT 2" # Use DIALECT 2 for vector search features
        )

        params = {"query_vector_bytes": query_vector_bytes}

        logging.debug(f"Executing FT.SEARCH query: {search_query} with vector length {len(query_vector_bytes)}")

        # 3. Execute the search query
        # Use execute_command as FalkorDB client might not wrap FT.SEARCH directly
        results = db.execute_command(search_query, params['query_vector_bytes']) # Pass bytes directly

        logging.debug(f"Raw FT.SEARCH results: {results}")

        # 4. Parse and format results
        # Results format: [count, result1, result2, ...]
        # result_i: [key, [score_field, score_value, text_field, text_value, ...]]
        formatted_chunks = []
        if results and isinstance(results, list) and len(results) > 1:
            num_results = results[0]
            logging.info(f"Found {num_results} potential matches.")
            for i in range(1, len(results), 2): # Step by 2 (key, fields)
                key = results[i]
                fields = results[i+1]
                chunk_data = {}
                # Parse the flat list of fields [field1_name, field1_value, field2_name, field2_value, ...]
                for j in range(0, len(fields), 2):
                    field_name = fields[j]
                    field_value = fields[j+1]
                    chunk_data[field_name] = field_value

                # Convert score (distance) to similarity if needed (e.g., 1 - distance for cosine)
                # The score here is distance, lower is better.
                score = float(chunk_data.get('__v_score', 1.0)) # Default to max distance if score missing

                formatted_chunks.append({
                    "text": chunk_data.get("text", ""),
                    "score": score, # Return the distance score directly
                    "metadata": {
                        "doc_id": chunk_data.get("doc_id", "unknown"),
                        "filename": chunk_data.get("filename", "unknown"),
                        "falkordb_key": key # Include the internal key if useful
                    }
                })
        else:
            logging.info("No relevant chunks found.")

        # Sort by score (ascending distance) just in case FT.SEARCH didn't
        formatted_chunks.sort(key=lambda x: x['score'])

        return formatted_chunks[:top_k] # Ensure we only return top_k

    except Exception as e:
        logging.error(f"Error retrieving relevant chunks: {e}", exc_info=True)
        # Depending on the error, might return empty list or raise exception
        return []