import logging
from typing import Optional

# Import necessary components
from app.core.models import get_llm
from app.core.rag_retriever import retrieve_relevant_chunks
from app.db.falkordb_client import get_db_connection
import torch # For tensor operations if needed

# Constants for prompting
MAX_INPUT_LENGTH = 1024 # Max tokens for Gemma input (adjust based on model limits)
MAX_NEW_TOKENS = 100   # Max tokens to generate for completion

async def generate_completion(
    current_text: str,
    full_document_context: Optional[str] = None,
    language: str = "ru",
    top_k_rag: int = 3 # Number of RAG chunks to retrieve
) -> str:
    """
    Generates text completion using Gemma, augmented with RAG context.
    """
    logging.info(f"Generating completion for language: {language}")
    model, tokenizer = get_llm()
    db = get_db_connection() # Get DB connection for RAG

    # 1. Retrieve RAG Context
    rag_context = ""
    try:
        # Use the end of the current text as the query for RAG
        query_text = current_text[-512:] # Use last 512 chars as query context
        relevant_chunks = await retrieve_relevant_chunks(query_text, top_k=top_k_rag, db=db)
        if relevant_chunks:
            rag_context = "\\n\\nRelevant Information:\\n" + "\\n---\\n".join([chunk['text'] for chunk in relevant_chunks])
            logging.info(f"Retrieved {len(relevant_chunks)} chunks from RAG.")
        else:
            logging.info("No relevant chunks found via RAG.")
    except Exception as e:
        logging.error(f"Error retrieving RAG context: {e}", exc_info=True)
        # Proceed without RAG context if retrieval fails

    # 2. Construct the Prompt
    # Combine available context, prioritizing current text and RAG results.
    # Truncate context intelligently to fit model limits.

    # Start with the most recent text
    prompt_text = current_text

    # Add RAG context if available, ensuring not to exceed limits too quickly
    if rag_context:
        available_space = MAX_INPUT_LENGTH - len(tokenizer.encode(prompt_text)) - 50 # Reserve space for instructions
        if available_space > 0:
            encoded_rag = tokenizer.encode(rag_context)
            truncated_rag_context = tokenizer.decode(encoded_rag[:available_space])
            prompt_text = truncated_rag_context + "\\n\\n" + prompt_text # Prepend RAG context

    # Add full document context if space permits (less priority than recent text/RAG)
    # if full_document_context:
    #     available_space = MAX_INPUT_LENGTH - len(tokenizer.encode(prompt_text)) - 50
    #     if available_space > 0:
    #         encoded_full_doc = tokenizer.encode(full_document_context)
    #         # Prioritize the end of the full document context if truncating
    #         truncated_full_doc = tokenizer.decode(encoded_full_doc[-available_space:])
    #         prompt_text = truncated_full_doc + "\\n\\n" + prompt_text # Prepend older context

    # Add instruction/task description (adjust based on Gemma's fine-tuning)
    # Using a format Gemma-IT might understand
    # Ensure the prompt clearly indicates the task is completion
    final_prompt = f"""<start_of_turn>user
Complete the following text in {language}. Continue writing naturally from the existing text.
Context:
{prompt_text}<end_of_turn>
<start_of_turn>model
""" # The model should continue after this

    # Truncate the final combined prompt if it's still too long
    encoded_prompt = tokenizer.encode(final_prompt)
    if len(encoded_prompt) > MAX_INPUT_LENGTH:
        logging.warning(f"Prompt exceeds max length ({len(encoded_prompt)} > {MAX_INPUT_LENGTH}). Truncating.")
        encoded_prompt = encoded_prompt[-MAX_INPUT_LENGTH:] # Keep the end of the prompt
        final_prompt = tokenizer.decode(encoded_prompt)
        # Ensure the prompt still ends correctly for the model
        if not final_prompt.endswith("<start_of_turn>model\n"):
             final_prompt = final_prompt[:final_prompt.rfind('<start_of_turn>')] + "<start_of_turn>model\n"

    logging.debug(f"Final prompt for completion (length {len(encoded_prompt)}):\n{final_prompt}")

    # 3. Generate Completion using Gemma
    try:
        inputs = tokenizer(final_prompt, return_tensors="pt", padding=False).to(model.device)

        # Generation parameters
        outputs = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            # Common parameters for completion:
            do_sample=True, # Enable sampling
            temperature=0.7, # Control randomness (lower = more deterministic)
            top_k=50,       # Consider top K tokens
            top_p=0.9,       # Nucleus sampling
            # pad_token_id=tokenizer.eos_token_id, # Important for stopping
            eos_token_id=tokenizer.eos_token_id,
            # Add other parameters as needed (repetition_penalty, etc.)
        )

        # Decode the generated tokens, skipping the prompt part
        generated_ids = outputs[0, inputs.input_ids.shape[1]:]
        suggestion = tokenizer.decode(generated_ids, skip_special_tokens=True)

        # Post-processing: remove potential artifacts, stop at newline if appropriate
        suggestion = suggestion.split("\n")[0] # Often good to stop at the first newline for completion
        suggestion = suggestion.strip()

        logging.info(f"Generated suggestion: '{suggestion[:100]}...'" )
        return suggestion

    except Exception as e:
        logging.error(f"Error during Gemma generation: {e}", exc_info=True)
        raise # Re-raise the exception to be handled by the router
