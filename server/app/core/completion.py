import asyncio
import logging
from typing import AsyncGenerator, Optional, List, Dict, Any
import uuid

from app.core.models import get_llm, get_embedding_pipeline
from app.core.rag_retriever import retrieve_relevant_chunks
from app.db.kuzudb_client import KuzuDBClient
from app.core.config import settings

# Constants for prompting
MAX_INPUT_LENGTH = 1024
MAX_NEW_TOKENS = 100

async def generate_completion_stream(
    current_text: str,
    full_document_context: Optional[str] = None,
    language: str = "ru",
    top_k_rag: int = 3,
    db: KuzuDBClient = None
) -> AsyncGenerator[str, None]:
    """
    Stream completions using a simple in-process approach.
    """
    # Ensure Chunk table exists (instantiate db if needed)
    close_db = False
    if db is None:
        db = KuzuDBClient(settings.KUZUDB_PATH)
        db.connect()
        close_db = True
    
    try:
        # Retrieve RAG Context
        rag_context = ""
        query_text = current_text[-512:]
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
            logging.error(f"Error retrieving RAG context: {e}")

        # Construct the Prompt text
        prompt_text = current_text
        if full_document_context:
            prompt_text = full_document_context + "\n\n" + prompt_text
        if rag_context:
            prompt_text = rag_context + "\n\n" + prompt_text

        # Prepare system and user messages for streaming
        const_system = f"You are a helpful assistant. Continue the text in {language}. Only generate the continuation, do not repeat any part of the input text."
        messages = [
            {"role": "system", "content": const_system},
            {"role": "user", "content": f"Complete this text. Only output the completion, not the input: {prompt_text}"}
        ]

        # Simple streaming directly from the LLM
        llm_model = get_llm()
        
        # Stream tokens directly
        token_count = 0
        logging.info(f"Starting stream generation for text: '{current_text[:30]}...'")
        for chunk in llm_model.create_chat_completion(
            messages=messages,
            max_tokens=MAX_NEW_TOKENS,
            temperature=0.7,
            stream=True
        ):
            if chunk and "choices" in chunk and len(chunk["choices"]) > 0:
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    token_count += 1
                    if token_count % 5 == 0 or token_count < 3:  # Log every 5th token or first few tokens
                        logging.info(f"Streaming token {token_count}: '{content}'")
                    yield content
        
        logging.info(f"Stream completed with {token_count} tokens generated.")
    
    except asyncio.CancelledError:
        logging.info("Stream cancelled by client")
    except Exception as e:
        logging.error(f"Error in completion stream: {e}")
        yield f"[Error: {str(e)}]"
    finally:
        # Close DB if we opened it
        if close_db and db:
            db.close()

async def generate_completion(
    current_text: str,
    full_document_context: Optional[str] = None,
    language: str = "ru",
    top_k_rag: int = 3,
    db: KuzuDBClient = None
) -> str:
    """
    Generate a complete text completion (non-streaming).
    """
    # Ensure Chunk table exists (instantiate db if needed)
    close_db = False
    if db is None:
        db = KuzuDBClient(settings.KUZUDB_PATH)
        db.connect()
        close_db = True
    
    try:
        # Retrieve RAG Context
        rag_context = ""
        try:
            # Check if documents exist
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
                    logging.info(f"🔍 Using {len(relevant_chunks)} chunks for completion")
                else:
                    logging.info("❌ No relevant chunks found via RAG.")
        except Exception as e:
            logging.error(f"Error retrieving RAG context: {e}")

        # Construct the Prompt text
        prompt_text = current_text
        if full_document_context:
            prompt_text = full_document_context + "\n\n" + prompt_text
        if rag_context:
            prompt_text = rag_context + "\n\n" + prompt_text

        # Prepare system and user messages
        const_system = f"You are a helpful assistant. Continue the text in {language}."
        messages = [
            {"role": "system", "content": const_system},
            {"role": "user", "content": f"Complete this text: {prompt_text}"}
        ]
    
        # Collect all tokens synchronously
        llm_model = get_llm()
        result_tokens = []
        
        for chunk in llm_model.create_chat_completion(
            messages=messages,
            max_tokens=MAX_NEW_TOKENS,
            temperature=0.7,
            stream=True
        ):
            if chunk and "choices" in chunk and chunk["choices"]:
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    result_tokens.append(content)
        
        return "".join(result_tokens)
        
    except Exception as e:
        logging.error(f"Error in completion: {e}")
        return f"[Error: {str(e)}]"
    finally:
        # Close DB if we opened it
        if close_db and db:
            db.close()