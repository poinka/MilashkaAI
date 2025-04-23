import asyncio
import multiprocessing
import logging
from typing import AsyncGenerator, Optional, List, Dict, Any

from app.core.models import get_llm, get_embedding_pipeline
from app.core.rag_retriever import retrieve_relevant_chunks
from app.db.kuzudb_client import get_db, KuzuDBClient
from app.core.config import settings

# Constants for prompting
MAX_INPUT_LENGTH = 1024
MAX_NEW_TOKENS = 100

# Safe streaming via subprocess worker
def _stream_worker(messages: List[Dict[str, Any]], queue: multiprocessing.Queue):
    try:
        logging.info("Stream worker starting...")
        llm_model = get_llm()
        logging.info("LLM model loaded, starting completion...")
        error_count = 0
        token_count = 0
        
        for chunk in llm_model.create_chat_completion(
            messages=messages,
            max_tokens=MAX_NEW_TOKENS,
            temperature=0.7,
            stream=True
        ):
            if error_count >= 3:  # Stop if too many queue errors
                logging.warning("Too many queue errors, stopping generation")
                break
                
            if chunk and "choices" in chunk and len(chunk["choices"]) > 0:
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    try:
                        # Use put_nowait to avoid blocking indefinitely
                        queue.put_nowait(content)
                        token_count += 1
                        logging.debug(f"Token: '{content}'")
                        error_count = 0  # Reset error count on success
                    except queue.Full:
                        error_count += 1
                        logging.warning(f"Queue full, attempt {error_count}")
                        try:
                            # Try one more time with a short timeout
                            queue.put(content, timeout=0.1)
                            error_count = 0
                        except (queue.Full, queue.TimeoutError):
                            # If still fails, client might be gone
                            if error_count >= 3:
                                logging.error("Client appears disconnected")
                                break
                    
                    if token_count >= MAX_NEW_TOKENS:
                        logging.info(f"Max tokens ({MAX_NEW_TOKENS}) reached")
                        break

        logging.info(f"Generation complete: {token_count} tokens streamed")
        queue.put(None)  # Signal completion
    except Exception as e:
        logging.error(f"Stream worker error: {str(e)}")
        try:
            queue.put(("__error__", str(e)))
            queue.put(None)
        except:
            pass  # Queue might be closed


# Global reference to the current streaming process for cancellation
current_stream_proc = None

def stop_current_stream():
    global current_stream_proc
    if current_stream_proc is not None and current_stream_proc.is_alive():
        current_stream_proc.terminate()
        current_stream_proc.join()
        current_stream_proc = None

async def generate_completion_stream(
    current_text: str,
    full_document_context: Optional[str] = None,
    language: str = "ru",
    top_k_rag: int = 3,
    db: KuzuDBClient = None
) -> AsyncGenerator[str, None]:
    global current_stream_proc
    """
    Safe streaming via subprocess to prevent SIGSEGV in main process.
    """

    # Ensure Chunk table exists (instantiate db if needed)
    close_db = False
    if db is None:
        db = KuzuDBClient(settings.KUZUDB_PATH)
        db.connect()
        close_db = True
    try:
        # Ensure Document table exists for RAG
        db.execute(f"""
            CREATE NODE TABLE IF NOT EXISTS Document (
                doc_id STRING PRIMARY KEY,
                filename STRING,
                status STRING,
                created_at STRING,
                updated_at STRING,
                processed_at STRING,
                error STRING
            )
        """)
        # Ensure Chunk table exists
        db.execute(f"""
            CREATE NODE TABLE IF NOT EXISTS Chunk (
                chunk_id STRING PRIMARY KEY,
                doc_id STRING,
                text STRING,
                embedding FLOAT[]
            )
        """)
    except Exception as e:
        logging.error(f"Failed to ensure Chunk table: {e}")
    finally:
        if close_db:
            db.close()

    # Retrieve RAG Context
    query_text = current_text[-512:]
    rag_context = ""
    try:
        # Check if documents exist
        doc_count = db.execute("MATCH (d:Document) RETURN count(*)").get_next()[0]
        if doc_count == 0:
            logging.info("No documents found in database for RAG.")
        else:
            relevant_chunks = await retrieve_relevant_chunks(
                query_text,
                get_embedding_pipeline(),
                db,
                top_k=top_k_rag
            )
            if relevant_chunks:
                rag_context = "\n\nRelevant Information:\n" + "\n---\n".join([chunk['text'] for chunk in relevant_chunks])
                logging.info(f"🔍 Using {len(relevant_chunks)} chunks for completion:")
                for i, chunk in enumerate(relevant_chunks):
                    logging.info(f"RAG Chunk {i+1} (Score: {chunk['score']:.4f}):\n{chunk['text']}\n")
            else:
                logging.info("❌ No relevant chunks found via RAG.")
    except Exception as e:
        logging.error(f"Error retrieving RAG context for query '{query_text[:50]}...': {e}")

    # Construct the Prompt text
    prompt_text = current_text
    if full_document_context:
        prompt_text = full_document_context + "\n\n" + prompt_text
    if rag_context:
        prompt_text = rag_context + "\n\n" + prompt_text

    # Prepare system and user messages for streaming
    const_system = f"You are a helpful assistant. Continue the text in {language}."
    messages = [
        {"role": "system", "content": const_system},
        {"role": "user", "content": f"Complete this text: {prompt_text}"}
    ]

    # Before starting new process, stop any previous one
    stop_current_stream()
    queue: multiprocessing.Queue = multiprocessing.Queue()
    proc = multiprocessing.Process(target=_stream_worker, args=(messages, queue))
    current_stream_proc = proc
    proc.start()
    loop = asyncio.get_event_loop()
    while True:
        token = await loop.run_in_executor(None, queue.get)
        if token is None:
            break
        if isinstance(token, tuple) and token[0] == "__error__":
            logging.error(f"Error in streaming subprocess: {token[1]}")
            yield f"[Error: {token[1]}]"
            break
        yield token
    proc.join()
    current_stream_proc = None
    return

async def generate_completion(
    current_text: str,
    full_document_context: Optional[str] = None,
    language: str = "ru",
    top_k_rag: int = 3,
    db: KuzuDBClient = None
) -> str:
    # Ensure Chunk table exists (instantiate db if needed)
    close_db = False
    if db is None:
        db = KuzuDBClient(settings.KUZUDB_PATH)
        db.connect()
        close_db = True
    try:
        # Ensure Document table exists for RAG
        db.execute(f"""
            CREATE NODE TABLE IF NOT EXISTS Document (
                doc_id STRING PRIMARY KEY,
                filename STRING,
                status STRING,
                created_at STRING,
                updated_at STRING,
                processed_at STRING,
                error STRING
            )
        """)
        # Ensure Chunk table exists
        db.execute(f"""
            CREATE NODE TABLE IF NOT EXISTS Chunk (
                chunk_id STRING PRIMARY KEY,
                doc_id STRING,
                text STRING,
                embedding FLOAT[]
            )
        """)
    except Exception as e:
        logging.error(f"Failed to ensure Chunk table: {e}")
    finally:
        if close_db:
            db.close()

    # Retrieve RAG Context
    rag_context = ""
    try:
        doc_count = db.execute("MATCH (d:Document) RETURN count(*)").get_next()[0]
        if doc_count == 0:
            logging.info("No documents found in database for RAG.")
        else:
            query_text = current_text[-512:]
            relevant_chunks = await retrieve_relevant_chunks(
                query_text,
                get_embedding_pipeline(),
                db,
                top_k=top_k_rag
            )
            if relevant_chunks:
                rag_context = "\n\nRelevant Information:\n" + "\n---\n".join([chunk['text'] for chunk in relevant_chunks])
                logging.info(f"🔍 Using {len(relevant_chunks)} chunks for completion:")
                for i, chunk in enumerate(relevant_chunks):
                    logging.info(f"RAG Chunk {i+1} (Score: {chunk['score']:.4f}):\n{chunk['text']}\n")
            else:
                logging.info("❌ No relevant chunks found via RAG.")
    except Exception as e:
        logging.error(f"Error retrieving RAG context for query '{{}}...': {{}}".format(current_text[:50], e))

    # Construct the Prompt text
    prompt_text = current_text
    if full_document_context:
        prompt_text = full_document_context + "\n\n" + prompt_text
    if rag_context:
        prompt_text = rag_context + "\n\n" + prompt_text
    const_system = f"You are a helpful assistant. Continue the text in {language}."
    messages = [
        {"role": "system", "content": const_system},
        {"role": "user", "content": f"Complete this text: {prompt_text}"}
    ]
    llm_model = get_llm()
    output = llm_model.create_chat_completion(
        messages=messages,
        max_tokens=MAX_NEW_TOKENS,
        temperature=0.7,
        stream=False
    )
    if "choices" in output and len(output["choices"]) > 0:
        suggestion = output["choices"][0]["message"]["content"].strip()
        return suggestion
    else:
        logging.error(f"Unexpected LLM output format: {output}")
        return ""