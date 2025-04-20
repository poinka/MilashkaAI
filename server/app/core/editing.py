import logging
from typing import Optional, Dict, Any
from fastapi import HTTPException
import asyncio
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

async def evaluate_edit_quality(
    model,
    tokenizer,
    original: str,
    edited: str,
    prompt: str,
    language: str
) -> float:
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
    try:
        inputs = tokenizer(
            eval_prompt,
            return_tensors="pt",
            truncation=True,
            max_length=settings.MAX_INPUT_LENGTH
        ).to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=10,
                temperature=0.1,
                do_sample=False,
                eos_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.eos_token_id
            )

        score_text = tokenizer.decode(
            outputs[0, inputs.input_ids.shape[1]:],
            skip_special_tokens=True
        )
        
        try:
            score = float(score_text.strip())
            return max(0.0, min(100.0, score)) / 100.0
        except ValueError:
            logging.warning(f"Could not parse score: {score_text}")
            return 0.5
    except Exception as e:
        logging.error(f"Error evaluating edit quality: {e}")
        return 0.5

async def generate_alternative_edits(
    model,
    tokenizer,
    text: str,
    prompt: str,
    language: str,
    num_alternatives: int = 3
) -> list[str]:
    alternatives = []
    base_prompt = f"""<start_of_turn>user
Edit the following text in {language} based on this request: "{prompt}"
Be creative but preserve the original meaning.

Text: "{text}"<end_of_turn>
<start_of_turn>model
Edited Text: """

    try:
        inputs = tokenizer(
            base_prompt,
            return_tensors="pt",
            truncation=True,
            max_length=settings.MAX_INPUT_LENGTH
        ).to(model.device)

        for i in range(num_alternatives):
            outputs = model.generate(
                **inputs,
                max_new_tokens=settings.MAX_NEW_TOKENS,
                temperature=0.8,
                top_p=0.9,
                do_sample=True,
                num_return_sequences=1,
                eos_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.eos_token_id
            )

            edited = tokenizer.decode(
                outputs[0, inputs.input_ids.shape[1]:],
                skip_special_tokens=True
            )
            edited = edited.strip().replace('"', '')
            
            if edited and edited not in alternatives:
                alternatives.append(edited)

        return alternatives
    except Exception as e:
        logging.error(f"Error generating alternatives: {e}")
        return []

async def perform_text_edit(
    selected_text: str,
    prompt: str,
    language: str = "ru",
    context_window: int = 1000,
    min_confidence: float = 0.7
) -> Dict[str, Any]:
    logging.info(f"Editing text (language: {language}, prompt: {prompt})")
    model, tokenizer = get_llm()
    edit_context = EditingContext(selected_text, prompt, language)

    try:
        # Ensure Chunk table exists
        db = get_db_connection()
        db.execute("""
            CREATE NODE TABLE IF NOT EXISTS Chunk (
                chunk_id STRING,
                doc_id STRING,
                text STRING,
                embedding VECTOR[FLOAT, 768],
                created_at STRING,
                PRIMARY KEY (chunk_id)
            )
        """)

        # Get RAG context
        doc_count = db.execute("MATCH (d:Document) RETURN count(*)").get_next()[0]
        rag_results = []
        if doc_count > 0:
            rag_results = await retrieve_relevant_chunks(
                selected_text,
                top_k=3,
                db=db,
                use_cache=True
            )
        else:
            logging.info("No documents found for RAG context.")
        rag_context = "\n".join([chunk["text"] for chunk in rag_results])

        # Construct prompt
        edit_prompt = f"""<start_of_turn>user
Edit the following text in {language} based on this request: "{prompt}"

Requirements:
1. Make only the requested changes
2. Preserve the original meaning and style
3. Maintain consistent formatting
4. Ensure grammatical correctness

Related context:
{rag_context[:context_window]}

Text to edit: "{selected_text}"<end_of_turn>
<start_of_turn>model
Edited Text: """

        # Generate primary edit
        async def generate_with_timeout():
            inputs = tokenizer(
                edit_prompt,
                return_tensors="pt",
                truncation=True,
                max_length=settings.MAX_INPUT_LENGTH
            ).to(model.device)

            return await asyncio.wait_for(
                asyncio.to_thread(
                    model.generate,
                    **inputs,
                    max_new_tokens=settings.MAX_NEW_TOKENS,
                    temperature=0.3,
                    do_sample=False,
                    eos_token_id=tokenizer.eos_token_id,
                    pad_token_id=tokenizer.eos_token_id
                ),
                timeout=settings.MODEL_TIMEOUT
            )

        outputs = await generate_with_timeout()
        edited_text = tokenizer.decode(
            outputs[0, inputs.input_ids.shape[1]:],
            skip_special_tokens=True
        )
        edited_text = edited_text.strip().replace('"', '')

        # Evaluate edit quality
        confidence = await evaluate_edit_quality(
            model,
            tokenizer,
            selected_text,
            edited_text,
            prompt,
            language
        )
        edit_context.add_edit(selected_text, edited_text, confidence)

        # Generate alternatives if needed
        alternatives = []
        if confidence < min_confidence:
            alternatives = await generate_alternative_edits(
                model,
                tokenizer,
                selected_text,
                prompt,
                language
            )

        result = {
            "edited_text": edited_text,
            "confidence": confidence,
            "alternatives": alternatives if alternatives else None
        }

        if confidence < min_confidence:
            result["warning"] = "Low confidence in edit quality. Consider reviewing alternatives."

        logging.info(f"Edit completed with confidence: {confidence:.2f}")
        return result

    except asyncio.TimeoutError:
        logging.error("Edit generation timed out")
        raise HTTPException(status_code=408, detail="Edit generation timed out")
    except Exception as e:
        logging.error(f"Error during text editing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to edit text: {str(e)}")