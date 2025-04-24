import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from app.db.kuzudb_client import KuzuDBClient, get_db
from app.schemas.models import CompletionRequest
from app.core.rag_retriever import retrieve_relevant_chunks
from app.core.models import embedding_pipeline
from app.core.completion import generate_completion, generate_completion_stream

from app.schemas.models import CompletionResponse
from app.schemas.errors import ErrorResponse

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

@router.post("/")
async def get_completion(request: CompletionRequest, db: KuzuDBClient = Depends(get_db)):
    try:
        context_chunks = await retrieve_relevant_chunks(
            query_text=request.current_text,
            embedding_pipeline=embedding_pipeline,
            db=db,
            top_k=3
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

@router.post("/stream")
async def stream_completion(request: CompletionRequest, db: KuzuDBClient = Depends(get_db)):
    try:
        context_chunks = await retrieve_relevant_chunks(
            query_text=request.current_text,
            embedding_pipeline=embedding_pipeline,
            db=db,
            top_k=3
        )
        if not context_chunks:
            logger.info("No relevant chunks found for the query")
        
        logger.info(f"Starting streaming completion for: '{request.current_text[:30]}...'")
        
        async def completion_generator():
            disconnected = False
            token_count = 0
            try:
                async for token in generate_completion_stream(
                    request.current_text,
                    request.full_document_context,
                    request.language
                ):
                    if disconnected:
                        logger.info("Client disconnected, stopping generation")
                        break
                    
                    token_count += 1
                    logger.debug(f"Sending token {token_count}: '{token}'")
                    
                    # Send the token immediately with flush directive
                    yield f"data: {token}\n\n"
                    
                    # Force a small wait to allow the client to process each token
                    # This prevents buffering and ensures tokens are sent one by one
                    await asyncio.sleep(0.01)
                
                logger.info(f"Completed streaming {token_count} tokens")
            except ConnectionResetError:
                logger.warning("Client connection reset")
                disconnected = True
            except Exception as e:
                logger.error(f"Stream error: {e}")
                raise
        
        logger.info("Streaming completion started")
        return StreamingResponse(
            completion_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    except Exception as e:
        logger.error(f"Stream setup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))