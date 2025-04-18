from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from app.core.config import settings
from app.schemas.models import CompletionRequest, CompletionResponse
from app.schemas.errors import ErrorResponse
from app.core.completion import generate_completion
from app.core.rag_retriever import retrieve_relevant_chunks
from app.db.kuzudb_client import get_db_connection

router = APIRouter(
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse}
    }
)

@router.post("/",
    response_model=CompletionResponse,
    summary="Generate text completion")
async def get_completion(request: CompletionRequest):
    """
    Generate a completion for the given text, using RAG context if available.
    """
    try:
        # Get relevant context from indexed documents
        db = get_db_connection()
        context_chunks = await retrieve_relevant_chunks(
            request.current_text,
            settings.RAG_TOP_K,
            db,
            use_cache=True
        )
        
        # Combine document context if provided
        context = ""
        if request.full_document_context:
            context += request.full_document_context + "\n\n"
        
        # Add retrieved chunks
        if context_chunks:
            context += "\n".join(chunk["text"] for chunk in context_chunks)
        
        # Generate completion
        completion = await generate_completion(
            request.current_text,
            context if context else None,
            request.language
        )
        
        # Calculate confidence based on context relevance
        confidence = 0.9 if context_chunks else 0.7
        
        # Build response metadata
        metadata = {
            "has_context": bool(context),
            "num_context_chunks": len(context_chunks) if context_chunks else 0
        }
        
        return CompletionResponse(
            suggestion=completion,
            confidence=confidence,
            metadata=metadata
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Completion generation failed: {str(e)}"
        )

@router.post("/stream",
    response_model=CompletionResponse,
    summary="Stream text completion")
async def stream_completion(request: CompletionRequest):
    """
    Stream completion tokens as they're generated.
    Returns a streaming response of completion chunks.
    """
    try:
        # Similar to regular completion but with streaming
        db = get_db_connection()
        context_chunks = await retrieve_relevant_chunks(
            request.current_text,
            settings.RAG_TOP_K,
            db,
            use_cache=True
        )
        
        # Combine context
        context = request.full_document_context or ""
        if context_chunks:
            context += "\n".join(chunk["text"] for chunk in context_chunks)
        
        async def completion_generator():
            async for token in generate_completion(
                request.current_text,
                context if context else None,
                request.language,
                stream=True
            ):
                yield token
        
        return StreamingResponse(
            completion_generator(),
            media_type="text/event-stream"
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Streaming completion failed: {str(e)}"
        )
