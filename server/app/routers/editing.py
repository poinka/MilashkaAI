from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
import logging

from app.core.config import settings
from app.schemas.models import EditRequest, EditResponse
from app.schemas.errors import ErrorResponse
from app.core.editing import perform_text_edit
from app.core.rag_retriever import retrieve_relevant_chunks

# Configure module logger
logger = logging.getLogger('app.routers.editing')

router = APIRouter(
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse}
    }
)

@router.post("/",
    response_model=EditResponse,
    summary="Edit text based on prompt")
async def edit_text(request: EditRequest):
    """
    Edit the selected text based on the provided prompt,
    using RAG context for better understanding.
    """
    try:
        logger.info(f"Processing edit request: prompt='{request.prompt}', text_length={len(request.selected_text)}")
        
        # Get relevant context
        context_chunks = await retrieve_relevant_chunks(
            request.selected_text,
            settings.RAG_TOP_K
        )
        logger.debug(f"Retrieved {len(context_chunks) if context_chunks else 0} context chunks")

        # Combine context chunks into a single string if needed by perform_text_edit
        context_text = "\n".join(chunk["text"] for chunk in context_chunks) if context_chunks else None

        # Perform edit, passing the combined context
        result = await perform_text_edit(
            request.selected_text,
            request.prompt,
            request.language,
            context_text=context_text,
            min_confidence=settings.RAG_SIMILARITY_THRESHOLD
        )

        logger.info(f"Edit completed successfully: confidence={result['confidence']:.2f}")
        if result.get('warning'):
            logger.warning(f"Edit warning: {result['warning']}")

        return EditResponse(
            edited_text=result["edited_text"],
            confidence=result["confidence"],
            alternatives=result.get("alternatives"),
            warning=result.get("warning")
        )

    except Exception as e:
        logger.error(f"Text editing failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Text editing failed: {str(e)}"
        )

@router.post("/preview",
    response_model=List[str],
    summary="Preview multiple edit alternatives")
async def preview_edits(request: EditRequest):
    """
    Generate multiple alternative edits for review before applying.
    """
    try:
        # Get relevant context
        context_chunks = await retrieve_relevant_chunks(
            request.selected_text,
            settings.RAG_TOP_K
        )

        # Generate multiple alternatives
        result = await perform_text_edit(
            request.selected_text,
            request.prompt,
            request.language,
            generate_alternatives=True,
            num_alternatives=3
        )

        alternatives = result.get("alternatives", [])
        if not alternatives:
            alternatives = [result["edited_text"]]

        return alternatives

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Preview generation failed: {str(e)}"
        )

@router.post("/evaluate",
    response_model=float,
    summary="Evaluate edit quality")
async def evaluate_edit(
    original: str,
    edited: str,
    prompt: str,
    language: str = "ru"
):
    """
    Evaluate the quality of an edit against the original prompt.
    Returns a confidence score between 0 and 1.
    """
    try:
        result = await perform_text_edit(
            original,
            prompt,
            language,
            evaluate_only=True,
            candidate_edit=edited
        )

        return result["confidence"]

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Edit evaluation failed: {str(e)}"
        )
