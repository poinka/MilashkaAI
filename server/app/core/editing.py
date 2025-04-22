import logging
from typing import Optional, Dict, Any, List
import asyncio
from fastapi import HTTPException
from app.core.models import get_llm
from app.core.rag_retriever import retrieve_relevant_chunks
from app.db.kuzudb_client import get_db_connection
from app.core.config import settings

class EditingContext:
    def __init__(self, text: str, prompt: str, language: str):
        self.text = text
        self.prompt = prompt
        self.language = language
        self.edits_history = []
        self.confidence_score = 0.0

    def add_edit(self, original: str, edited: str, score: float):
        self.edits_history.append({
            "original": original,
            "edited": edited,
            "score": score,
            "timestamp": asyncio.get_running_loop().time()
        })
        self.confidence_score = score

async def simple_evaluate_quality(llm_model, original: str, edited: str, prompt: str, language: str) -> float:
    """
    Simplified evaluation function that works with the Llama.cpp model
    """
    # If no edit was made, low confidence
    if original == edited:
        return 0.3
    
    # Basic length checks
    if len(edited) < len(original) * 0.5 or len(edited) > len(original) * 2:
        return 0.5  # Suspicious if length changed dramatically
    
    try:
        # Try to use the model for a simple quality check if possible
        eval_prompt = f"""<start_of_turn>user
Rate how well this edit matches the requested changes in {language}.
Original text: "{original}"
Edit request: "{prompt}"
Edited text: "{edited}"

Rate from 0 to 100 where:
0: Completely ignores the request or changes meaning
100: Perfect edit that fulfills the request while preserving intent

Output only the number.<end_of_turn>
<start_of_turn>model
"""
        output = llm_model.create_completion(
            prompt=eval_prompt,
            max_tokens=512,
            temperature=0.1,
            top_k=1,
            top_p=0.9,
            stop=["<end_of_turn>", "<start_of_turn>user"]
        )
        
        if "choices" in output and len(output["choices"]) > 0:
            score_text = output["choices"][0]["text"].strip()
            try:
                score = float(score_text.split()[0].replace(',', ''))
                return max(0.0, min(100.0, score)) / 100.0
            except (ValueError, IndexError):
                logging.warning(f"Could not parse score: {score_text}")
                return 0.7  # Default to somewhat confident
        return 0.7  # Default to somewhat confident
    except Exception as e:
        logging.error(f"Error evaluating edit quality: {str(e)}")
        return 0.7  # Default to somewhat confident

async def generate_alternative_edits(
    llm_model,
    text: str,
    prompt: str,
    language: str,
    num_alternatives: int = 3
) -> List[str]:
    alternatives = []
    base_prompt = f"""<start_of_turn>user
Edit the following text in {language} based on this request: "{prompt}"
Be creative but preserve the original meaning.

Text: "{text}"<end_of_turn>
<start_of_turn>model
Edited Text: """

    try:
        # Generate a couple alternatives with different temperatures
        for temp in [0.5, 0.7]:
            try:
                output = llm_model.create_completion(
                    prompt=base_prompt,
                    max_tokens=settings.MAX_NEW_TOKENS,
                    temperature=temp,
                    top_k=50,
                    top_p=0.9,
                    stop=["<end_of_turn>", "<start_of_turn>user"]
                )
                
                if "choices" in output and len(output["choices"]) > 0:
                    edited = output["choices"][0]["text"].strip().replace('"', '')
                    if edited and edited not in alternatives:
                        alternatives.append(edited)
            except Exception as e:
                logging.error(f"Error generating alternative with temp={temp}: {str(e)}")
                continue
                
        return alternatives
    except Exception as e:
        logging.error(f"Error generating alternatives: {str(e)}")
        return []

async def perform_text_edit(
    selected_text: str, 
    prompt: str, 
    language: str, 
    context_text: Optional[str] = None, # Added context_text parameter
    min_confidence: float = 0.7
) -> Dict[str, Any]:
    """
    Performs text editing using the LLM, potentially incorporating RAG context.
    """
    llm = get_llm()
    if not llm:
        raise HTTPException(status_code=503, detail="LLM not available")

    # Construct the prompt for the LLM
    system_prompt = f"""You are an expert text editor. Edit the following text in {language} based ONLY on the user's request. Preserve the original meaning and tone unless requested otherwise. Output ONLY the edited text, without explanations or apologies."""
    
    user_prompt_parts = [
        f"Original text: \"{selected_text}\"",
        f"Edit request: \"{prompt}\""
    ]
    
    # Add context if available
    if context_text:
        # Ensure context doesn't make the prompt too long (approximate check)
        max_context_len = settings.MAX_INPUT_LENGTH - (len(system_prompt) + len(selected_text) + len(prompt) + 100) 
        truncated_context = context_text[:max_context_len]
        user_prompt_parts.insert(0, f"Relevant context from document:\n{truncated_context}\n---")
        
    full_user_prompt = "\n".join(user_prompt_parts)

    # Use the chat template structure expected by the model
    chat_prompt = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": full_user_prompt}
    ]

    try:
        # Generate the edited text
        response = llm.create_chat_completion(
            messages=chat_prompt,
            max_tokens=settings.MAX_OUTPUT_LENGTH, 
            temperature=0.5, # Adjust temperature for creativity vs faithfulness
            stop=["<end_of_turn>"] # Ensure model stops appropriately
        )
        
        edited_text = response['choices'][0]['message']['content'].strip()
        
        # Basic check if the model refused or produced empty output
        if not edited_text or "cannot fulfill" in edited_text.lower() or len(edited_text) < 2:
             edited_text = selected_text # Fallback to original if edit failed
             confidence = 0.2
             warning = "LLM could not perform the requested edit."
        else:
            # Evaluate quality (using the simplified function)
            confidence = await simple_evaluate_quality(llm, selected_text, edited_text, prompt, language)
            warning = None
            if confidence < min_confidence:
                warning = f"Edit confidence ({confidence:.2f}) is below threshold ({min_confidence}). Review carefully."

        return {
            "edited_text": edited_text,
            "confidence": confidence,
            "alternatives": [], # Placeholder for potential future alternatives
            "warning": warning
        }

    except Exception as e:
        logging.error(f"Error during text editing with LLM: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Text editing failed: {str(e)}")