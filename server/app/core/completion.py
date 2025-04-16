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
    Generates text completion using llama.cpp Gemma, augmented with RAG context.
    """
    logging.info(f"Generating completion for language: {language}")
    llm_model = get_llm()
    db = get_db_connection() # Get DB connection for RAG

    # 1. Retrieve RAG Context
    rag_context = ""
    try:
        query_text = current_text[-512:]
        relevant_chunks = await retrieve_relevant_chunks(query_text, top_k=top_k_rag, db=db)
        if relevant_chunks:
            rag_context = "\n\nRelevant Information:\n" + "\n---\n".join([chunk['text'] for chunk in relevant_chunks])
            logging.info(f"Retrieved {len(relevant_chunks)} chunks from RAG.")
        else:
            logging.info("No relevant chunks found via RAG.")
    except Exception as e:
        logging.error(f"Error retrieving RAG context: {e}", exc_info=True)

    # 2. Construct the Prompt
    prompt_text = current_text
    if rag_context:
        prompt_text = rag_context + "\n\n" + prompt_text

    final_prompt = f"""<start_of_turn>user\nComplete the following text in {language}. Continue writing naturally from the existing text.\nContext:\n{prompt_text}<end_of_turn>\n<start_of_turn>model\n"""

    logging.debug(f"Final prompt for completion:\n{final_prompt}")

    # 3. Generate Completion using llama.cpp
    try:
        output = llm_model(
            final_prompt,
            max_tokens=100,
            temperature=0.7,
            top_k=50,
            top_p=0.9,
            stop=["<end_of_turn>", "<start_of_turn>user"]
        )
        suggestion = output["choices"][0]["text"].strip()
        suggestion = suggestion.split("\n")[0].strip()
        logging.info(f"Generated suggestion: '{suggestion[:100]}...'")
        return suggestion
    except Exception as e:
        logging.error(f"Error during llama.cpp generation: {e}", exc_info=True)
        raise
