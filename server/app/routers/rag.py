from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
import asyncio

from app.core.config import settings
from app.core.rag_retriever import retrieve_relevant_chunks
from app.core.rag_builder import reindex_document
from app.db.kuzudb_client import get_db_connection

router = APIRouter()

@router.get("/search",
    summary="Search through indexed documents")
async def search_documents(
    query: str,
    top_k: int = Query(default=5, le=20),
    doc_id: Optional[str] = None,
    min_similarity: float = Query(
        default=settings.RAG_SIMILARITY_THRESHOLD,
        ge=0.0,
        le=1.0
    )
):
    """
    Search through indexed documents using vector similarity.
    Optionally filter by document ID and adjust similarity threshold.
    """
    try:
        db = get_db_connection()
        results = await retrieve_relevant_chunks(
            query,
            top_k,
            db,
            filter_doc_id=doc_id,
            similarity_threshold=min_similarity,
            use_cache=True
        )
        
        return {
            "results": results,
            "total": len(results),
            "metadata": {
                "query": query,
                "top_k": top_k,
                "doc_id": doc_id,
                "min_similarity": min_similarity
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {str(e)}"
        )

@router.post("/reindex/{doc_id}",
    summary="Reindex a specific document")
async def reindex_doc(doc_id: str):
    """
    Reindex a specific document to update its vectors and chunks.
    """
    try:
        db = get_db_connection()
        result = await reindex_document(doc_id, db)
        return {
            "success": True,
            "doc_id": doc_id,
            "chunks_indexed": result.get("chunks_indexed", 0)
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Reindexing failed: {str(e)}"
        )

@router.get("/similar",
    summary="Find similar text chunks")
async def find_similar(
    text: str,
    top_k: int = Query(default=5, le=20),
    exclude_doc_id: Optional[str] = None
):
    """
    Find similar text chunks across all indexed documents.
    Optionally exclude a specific document.
    """
    try:
        db = get_db_connection()
        results = await retrieve_relevant_chunks(
            text,
            top_k,
            db,
            exclude_doc_id=exclude_doc_id,
            use_cache=True
        )
        
        return {
            "similar_chunks": results,
            "total": len(results)
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Similarity search failed: {str(e)}"
        )

@router.post("/refresh-embeddings",
    summary="Refresh embeddings for all documents")
async def refresh_embeddings(
    batch_size: int = Query(default=10, le=50)
):
    """
    Refresh embeddings for all indexed documents.
    Uses batching to handle large collections efficiently.
    """
    try:
        db = get_db_connection()
        stats = {
            "documents_processed": 0,
            "chunks_updated": 0,
            "errors": []
        }

        # Implementation would iterate through documents
        # and update embeddings in batches
        
        return stats

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Embedding refresh failed: {str(e)}"
        )
