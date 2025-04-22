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
                embedding VECTOR[768],
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
            relevant_chunks = await retrieve_relevant_chunks(query_text, top_k=top_k_rag)
            if relevant_chunks:
                rag_context = "\n\nRelevant Information:\n" + "\n---\n".join([chunk['text'] for chunk in relevant_chunks])
                logging.info(f"🔍 Using {len(relevant_chunks)} chunks for completion:")
                for i, chunk in enumerate(relevant_chunks):
                    logging.info(f"RAG Chunk {i+1} (Score: {chunk['score']:.4f}):\n{chunk['text']}\n")
            else:
                logging.info("❌ No relevant chunks found via RAG.")
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
        # Debug the model interface
        logging.debug(f"LLM model type: {type(llm_model).__name__}")
        
        # Llama.cpp compatible parameters
        output = llm_model.create_completion(
            prompt=final_prompt,
            max_tokens=MAX_NEW_TOKENS,
            temperature=0.7,
            top_k=50,
            top_p=0.9,
            stop=["<end_of_turn>", "<start_of_turn>user"]
        )
        
        logging.debug(f"Raw LLM output: {output}")
        
        if "choices" in output and len(output["choices"]) > 0:
            suggestion = output["choices"][0]["text"].strip()
            suggestion = suggestion.split("\n")[0].strip()
            logging.info(f"Generated suggestion: '{suggestion[:100]}...'")
            return suggestion
        else:
            logging.error(f"Unexpected LLM output format: {output}")
            return ""  # Return empty string instead of crashing
    except Exception as e:
        logging.error(f"Error during LLM generation: {str(e)}", exc_info=True)
        # Return an empty string rather than raising an exception to prevent 500 errors
        return ""

async def generate_completion_stream(
    current_text: str,
    full_document_context: Optional[str] = None,
    language: str = "ru",
    top_k_rag: int = 3
):
    """
    Generates text completion using Gemma, yielding tokens as they're generated.
    
    Returns an async generator that yields tokens incrementally with detailed logging.
    """
    logging.info(f"🚀 Starting STREAMING completion for language: {language}")
    logging.info(f"📄 User input text: {current_text[:50]}..." if len(current_text) > 50 else f"📄 User input text: {current_text}")
    
    llm_model = get_llm()
    
    if not llm_model:
        logging.error("❌ LLM model not available")
        raise Exception("LLM model not available")
        
    db = get_db_connection()

    # Similar to generate_completion, but will stream results
    # Retrieve RAG Context
    rag_context = ""
    try:
        # Check if documents exist
        doc_count = db.execute("MATCH (d:Document) RETURN count(*)").get_next()[0]
        logging.info(f"📚 Found {doc_count} documents in database")
        
        if doc_count > 0:
            query_text = current_text[-512:]
            relevant_chunks = await retrieve_relevant_chunks(query_text, top_k=top_k_rag)
            if relevant_chunks:
                rag_context = "\n\nRelevant Information:\n" + "\n---\n".join([chunk['text'] for chunk in relevant_chunks])
                logging.info(f"🔍 Retrieved {len(relevant_chunks)} relevant chunks from RAG")
                for i, chunk in enumerate(relevant_chunks):
                    logging.info(f"  📎 Chunk {i+1}: {chunk['text'][:50]}...")
            else:
                logging.info("🔍 No relevant chunks found via RAG")
    except Exception as e:
        logging.error(f"❌ Error retrieving chunks: {e}")

    # Construct the prompt just like in generate_completion
    prompt_text = current_text
    if full_document_context:
        prompt_text = full_document_context + "\n\n" + prompt_text
        logging.info(f"📝 Added document context to prompt (now {len(prompt_text)} chars)")
    if rag_context:
        prompt_text = rag_context + "\n\n" + prompt_text
        logging.info(f"📝 Added RAG context to prompt (now {len(prompt_text)} chars)")

    # System prompt based on language
    system_message = f"You are a helpful assistant. Continue the text in {language}."
    logging.info(f"💬 System message: {system_message}")
    
    # Create chat format expected by the model
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": f"Complete this text: {prompt_text}"}
    ]
    
    # Stream the response
    try:
        logging.info("🔄 Starting model token generation...")
        completion = llm_model.create_chat_completion(
            messages=messages,
            max_tokens=MAX_NEW_TOKENS,
            temperature=0.7,
            stream=True  # Enable streaming
        )
        
        # Counter for tracking tokens
        token_count = 0
        generated_text = ""
        
        # Yield tokens as they arrive
        for chunk in completion:
            if chunk and "choices" in chunk and len(chunk["choices"]) > 0:
                # Extract token from the completion chunk 
                delta = chunk["choices"][0].get("delta", {})
                if "content" in delta and delta["content"]:
                    token = delta["content"]
                    token_count += 1
                    generated_text += token
                    
                    # Log every token for real-time visibility
                    if token_count % 5 == 0 or len(token) > 1:  # Log every 5th token or longer tokens
                        logging.info(f"🔤 Token #{token_count}: '{token}' (Current text: '{generated_text[-50:] if len(generated_text) > 50 else generated_text}')")
                    
                    yield token
        
        logging.info(f"✅ Completion finished. Generated {token_count} tokens: '{generated_text}'")
    except Exception as e:
        logging.error(f"❌ Error during streaming completion: {e}")
        yield f"[Error: {str(e)}]"