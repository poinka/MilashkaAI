import logging
from typing import Optional, Dict, Any, List
import asyncio
from fastapi import HTTPException
from app.core.models import get_llm

# Configure module logger
logger = logging.getLogger('app.core.editing')

async def perform_text_edit(
    selected_text: str, 
    prompt: str, 
    language: str, 
    context_text: Optional[str] = None,
    min_confidence: float = 0.0
) -> Dict[str, Any]:
    """
    Performs text editing using the LLM, incorporating RAG context for better understanding.
    """
    llm = get_llm()
    if not llm:
        logger.error("LLM not available")
        raise HTTPException(status_code=503, detail="LLM not available")

    logger.info(f"Starting text edit: prompt='{prompt}', text_length={len(selected_text)}")
    if context_text:
        logger.debug(f"Using context of length {len(context_text)}")

    try:
        # Construct the prompt for the LLM
        system_prompt = f"""You are an expert text editor. Edit the following text in {language} based ONLY on the user's request. Preserve the original meaning and tone unless requested otherwise. Output ONLY the edited text, without explanations or apologies."""
        
        user_prompt_parts = [
            f"Original text: \"{selected_text}\"",
            f"Edit request: \"{prompt}\""
        ]
        
        # Add context if available
        if context_text:
            # Ensure context doesn't make the prompt too long (approximate check)
            max_context_len = 2048 - (len(system_prompt) + len(selected_text) + len(prompt) + 100) 
            truncated_context = context_text[:max_context_len]
            user_prompt_parts.insert(0, f"Relevant context:\n{truncated_context}\n---")
            
        full_user_prompt = "\n".join(user_prompt_parts)

        chat_prompt = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_user_prompt}
        ]

        logger.debug("Sending edit request to LLM")
        response = llm.create_chat_completion(
            messages=chat_prompt,
            max_tokens=len(selected_text) * 2,  # Conservative estimate
            temperature=0.3,  # Lower temperature for more reliable edits
            stop=["<end_of_turn>"]
        )
        
        # Ensure we extract the text from the response properly
        edited_text = response['choices'][0]['message']['content'].strip()
        logger.debug(f"Received edited text of length {len(edited_text)}")
        
        if not edited_text or "cannot fulfill" in edited_text.lower() or len(edited_text) < 2:
            logger.warning("LLM produced invalid or empty edit")
            return {
                "edited_text": selected_text,
                "confidence": 0.2,
                "warning": "LLM could not perform the requested edit."
            }
        
        # Simple length-based sanity check
        if len(edited_text) < len(selected_text) * 0.5 or len(edited_text) > len(selected_text) * 2:
            logger.warning(f"Edit produced unusual length change: original={len(selected_text)}, edited={len(edited_text)}")
        
        logger.info("Edit completed successfully")
        return {
            "edited_text": edited_text,
            "confidence": 1.0,
            "alternatives": []
        }

    except Exception as e:
        logger.error(f"Error during text editing: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Text editing failed: {str(e)}")