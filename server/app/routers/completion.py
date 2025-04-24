from typing import Optional, AsyncGenerator
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import asyncio

from app.schemas.models import CompletionRequest, CompletionResponse, CompletionStreamResponse
from app.core.completion import generate_completion, generate_completion_stream
from app.core.config import settings
from app.db.kuzudb_client import get_db, KuzuDBClient

logger = logging.getLogger('app.routers.completion')
router = APIRouter()

@router.post("/", response_model=CompletionResponse)
async def create_completion(
    request: CompletionRequest,
    db: KuzuDBClient = Depends(get_db)
):
    """Get completion for the given text with RAG support"""
    try:
        request_id = f"req-{hex(hash(request.text) % 10000)[2:]}"
        
        logger.info(f"[{request_id}] Processing completion request")
        logger.info(f"[{request_id}] Input text: '{request.text}'")
        logger.info(f"[{request_id}] Language: {request.language}")
        
        # Get completion with RAG context
        completion = await generate_completion(
            current_text=request.text,
            language=request.language,
            top_k_rag=settings.RAG_TOP_K,
            db=db
        )
        
        logger.info(f"Completion generated successfully, length: {len(completion)}")
        return CompletionResponse(completion=completion)
        
    except Exception as e:
        logger.error(f"Completion failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Completion failed: {str(e)}"
        )

@router.post("/stream")
async def stream_completion(
    request: CompletionRequest,
    db: KuzuDBClient = Depends(get_db)
) -> StreamingResponse:
    """Stream completion for the given text with RAG support"""
    try:
        request_id = f"req-{hex(hash(request.text) % 10000)[2:]}"
        
        logger.info(f"[{request_id}] Starting streaming completion")
        logger.info(f"[{request_id}] Input text: '{request.text}'")
        logger.info(f"[{request_id}] Language: {request.language}")
        
        # Create streaming response with RAG
        return StreamingResponse(
            generate_completion_stream(
                current_text=request.text,
                language=request.language,
                top_k_rag=settings.RAG_TOP_K,
                db=db
            ),
            media_type="text/event-stream"
        )
        
    except Exception as e:
        logger.error(f"Stream completion failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Stream completion failed: {str(e)}"
        )