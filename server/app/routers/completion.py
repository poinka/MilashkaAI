import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional

from app.core.config import settings
from app.schemas.models import CompletionRequest, CompletionResponse
from app.schemas.errors import ErrorResponse
from app.core.completion import generate_completion
from app.core.rag_retriever import retrieve_relevant_chunks

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
logger.info("Logging configured for completion.py")

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
    logger.info(f"Handling POST /api/v1/completion/ request with current_text: {request.current_text}")
    try:
        # Get relevant context from indexed documents
        context_chunks = await retrieve_relevant_chunks(
            request.current_text,
            settings.RAG_TOP_K
        )
        if not context_chunks:
            logger.info("No relevant chunks found for the query")
        else:
            logger.debug(f"Retrieved {len(context_chunks)} context chunks: {context_chunks}")
        
        # Combine document context if provided
        context = ""
        if request.full_document_context:
            logger.debug(f"Adding full_document_context: {request.full_document_context}")
            context += request.full_document_context + "\n\n"
        
        # Add retrieved chunks
        if context_chunks:
            logger.debug("Adding retrieved chunks to context")
            context += "\n".join(chunk["text"] for chunk in context_chunks)
        logger.debug(f"Final context: {context}")
        
        # Generate completion
        logger.debug(f"Generating completion for language: {request.language}")
        completion = await generate_completion(
            request.current_text,
            context if context else None,
            request.language
        )
        logger.debug(f"Generated completion: {completion}")
        
        confidence = 0.9 if context_chunks else 0.7
        logger.debug(f"Calculated confidence: {confidence}")
        
        metadata = {
            "has_context": bool(context),
            "num_context_chunks": len(context_chunks) if context_chunks else 0
        }
        logger.debug(f"Response metadata: {metadata}")
        
        response = CompletionResponse(
            suggestion=completion,
            confidence=confidence,
            metadata=metadata
        )
        logger.info("Completion generated successfully")
        return response

    except Exception as e:
        logger.error(f"Completion generation failed: {str(e)}", exc_info=True)
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
    logger.info(f"Handling POST /api/v1/completion/stream request with current_text: {request.current_text}")
    try:
        logger.debug(f"Retrieving relevant chunks with top_k={settings.RAG_TOP_K}")
        context_chunks = await retrieve_relevant_chunks(
            request.current_text,
            settings.RAG_TOP_K
        )
        if not context_chunks:
            logger.info("No relevant chunks found for the query")
        else:
            logger.debug(f"Retrieved {len(context_chunks)} context chunks: {context_chunks}")
        
        # Combine context
        context = request.full_document_context or ""
        if context_chunks:
            logger.debug("Adding retrieved chunks to context")
            context += "\n".join(chunk["text"] for chunk in context_chunks)
        logger.debug(f"Final context: {context}")
        
        async def completion_generator():
            logger.debug(f"Starting streaming completion for language: {request.language}")
            async for token in generate_completion(
                request.current_text,
                context if context else None,
                request.language,
                stream=True
            ):
                logger.debug(f"Streaming token: {token}")
                yield token
        
        logger.info("Streaming completion started")
        return StreamingResponse(
            completion_generator(),
            media_type="text/event-stream"
        )

    except Exception as e:
        logger.error(f"Streaming completion failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Streaming completion failed: {str(e)}"
        )