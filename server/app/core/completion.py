import logging
from typing import Optional
from app.core.models import get_llm
from app.core.rag_retriever import retrieve_relevant_chunks
from app.db.kuzudb_client import get_db_connection

# Constants for prompting
MAX_INPUT_LENGTH = 1024
MAX_NEW_TOKENS = 100

async def generate_completion(
    current_text: str,
    full_document_context: Optional[str] = None,
    language: str = "ru",
    top_k_rag: int = 3
) -> str:
    """
    Generates text completion using Gemma, augmented with RAG context from Kùzu.
    """
    logging.info(f"Generating completion for language: {language}")
    llm_model = get_llm()
    db = get_db_connection()

    # Ensure Chunk table exists
    try:
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
    except Exception as e:
        logging.error(f"Failed to ensure Chunk table: {e}")

    # Retrieve RAG Context
    rag_context = ""
    try:
        # Check if documents exist
        doc_count = db.execute("MATCH (d:Document) RETURN count(*)").get_next()[0]
        if doc_count == 0:
            logging.info("No documents found in database for RAG.")
        else:
            query_text = current_text[-512:]
            relevant_chunks = await retrieve_relevant_chunks(query_text, top_k=top_k_rag, db=db)
            if relevant_chunks:
                rag_context = "\n\nRelevant Information:\n" + "\n---\n".join([chunk['text'] for chunk in relevant_chunks])
                logging.info(f"Retrieved {len(relevant_chunks)} chunks from RAG.")
            else:
                logging.info("No relevant chunks found via RAG.")
    except Exception as e:
        logging.error(f"Error retrieving RAG context for query '{query_text[:50]}...': {e}")

    # Construct the Prompt
    prompt_text = current_text
    if rag_context:
        prompt_text = rag_context + "\n\n" + prompt_text

    final_prompt = f"""<start_of_turn>user\nComplete the following text in {language}. Continue writing naturally from the existing text.\nContext:\n{prompt_text}<end_of_turn>\n<start_of_turn>model\n"""

    logging.debug(f"Final prompt for completion: {final_prompt[:200]}...")

    # Generate Completion
    try:
        output = llm_model(
            final_prompt,
            max_tokens=MAX_NEW_TOKENS,
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
        logging.error(f"Error during Gemma generation: {e}")
        raise