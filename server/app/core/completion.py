import asyncio
import logging
from typing import AsyncGenerator, Optional, List, Dict, Any
import uuid

from app.core.models import get_llm, get_embedding_pipeline
from app.core.rag_retriever import retrieve_relevant_chunks
from app.db.kuzudb_client import KuzuDBClient
from app.core.config import settings
from app.core.completion_config import CompletionConfig, CompletionPrompts

logger = logging.getLogger('app.core.completion')
config = CompletionConfig()

async def generate_completion_stream(
    current_text: str,
    full_document_context: Optional[str] = None,
    language: str = "ru",
    top_k_rag: int = 3,
    db: KuzuDBClient = None
) -> AsyncGenerator[str, None]:
    """Stream completions using RAG for enhanced context."""
    request_id = str(uuid.uuid4())[:8]
    close_db = False
    
    try:
        # Set up database if needed
        if db is None:
            db = KuzuDBClient(settings.KUZUDB_PATH)
            db.connect()
            close_db = True
        
        # Retrieve RAG Context
        rag_context = ""
        query_text = current_text[-config.RAG_MAX_QUERY_LENGTH:]
        try:
            # Check if documents exist
            doc_count = db.execute("MATCH (d:Document) RETURN count(*)").get_next()[0]
            if doc_count == 0:
                logger.info(f"[{request_id}] No documents found for RAG")
            else:
                relevant_chunks = await retrieve_relevant_chunks(
                    query_text,
                    get_embedding_pipeline(),
                    db,
                    top_k=top_k_rag
                )
                if relevant_chunks:
                    rag_context = "\n\nRelevant Information:\n" + "\n---\n".join([chunk['text'] for chunk in relevant_chunks])
                    logger.info(f"[{request_id}] 🔍 Found {len(relevant_chunks)} relevant chunks:")
                    for i, chunk in enumerate(relevant_chunks):
                        logger.debug(f"[{request_id}] RAG Chunk {i+1} (Score: {chunk['score']:.4f}):\n{chunk['text']}")
                else:
                    logger.info(f"[{request_id}] ❌ No relevant chunks found")
        except Exception as e:
            logger.error(f"[{request_id}] RAG retrieval failed: {str(e)}")

        # Construct prompt with context
        prompt_text = current_text
        if full_document_context:
            prompt_text = full_document_context + "\n\n" + prompt_text
        if rag_context:
            prompt_text = rag_context + "\n\n" + prompt_text

        # Prepare messages for LLM
        messages = [
            {
                "role": "system",
                "content": CompletionPrompts.SYSTEM_TEMPLATE.format(
                    language=language,
                    streaming_guide=CompletionPrompts.SYSTEM_STREAMING_GUIDE
                )
            },
            {
                "role": "user",
                "content": CompletionPrompts.USER_TEMPLATE.format(
                    streaming_note=CompletionPrompts.USER_STREAMING_NOTE,
                    text=prompt_text
                )
            }
        ]

        # Log LLM input
        logger.info(f"[{request_id}] LLM Input:")
        for msg in messages:
            logger.info(f"[{request_id}] [{msg['role'].upper()}] {msg['content'][:100]}...")

        # Stream from LLM with request tracking
        llm_model = get_llm()
        token_count = 0
        full_response = []
        
        logger.info(f"[{request_id}] Starting token stream generation")
        # Pass request_id to LLM for tracking
        for chunk in llm_model.create_chat_completion(
            messages=messages,
            max_tokens=config.MAX_NEW_TOKENS,
            temperature=config.TEMPERATURE,
            stream=True,
            request_id=request_id
        ):
            if chunk and "choices" in chunk and len(chunk["choices"]) > 0:
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    token_count += 1
                    full_response.append(content)
                    # Log EVERY token for thorough debugging
                    logger.debug(f"[{request_id}] Token {token_count}: '{content}'")
                    # Log hex representation to catch invisible characters/whitespace
                    logger.debug(f"[{request_id}] Token {token_count} (hex): {content.encode().hex()}")
                    yield content

        logger.info(f"[{request_id}] Stream completed: {token_count} tokens generated")
        logger.info(f"[{request_id}] Full response: {''.join(full_response)}")
    
    except asyncio.CancelledError:
        logger.info(f"[{request_id}] Stream cancelled by client")
        raise
    except Exception as e:
        logger.error(f"[{request_id}] Stream error: {str(e)}", exc_info=True)
        yield f"[Error: {str(e)}]"
    finally:
        if close_db and db:
            db.close()

async def generate_completion(
    current_text: str,
    full_document_context: Optional[str] = None,
    language: str = "ru",
    top_k_rag: int = 3,
    db: KuzuDBClient = None
) -> str:
    """Generate a complete text completion using RAG."""
    request_id = str(uuid.uuid4())[:8]
    close_db = False
    
    try:
        # Set up database if needed
        if db is None:
            db = KuzuDBClient(settings.KUZUDB_PATH)
            db.connect()
            close_db = True
        
        # Retrieve RAG Context
        rag_context = ""
        query_text = current_text[-config.RAG_MAX_QUERY_LENGTH:]
        try:
            # Check if documents exist
            doc_count = db.execute("MATCH (d:Document) RETURN count(*)").get_next()[0]
            if doc_count == 0:
                logger.info(f"[{request_id}] No documents found for RAG")
            else:
                relevant_chunks = await retrieve_relevant_chunks(
                    query_text,
                    get_embedding_pipeline(),
                    db,
                    top_k=top_k_rag
                )
                if relevant_chunks:
                    rag_context = "\n\nRelevant Information:\n" + "\n---\n".join([chunk['text'] for chunk in relevant_chunks])
                    logger.info(f"[{request_id}] 🔍 Found {len(relevant_chunks)} relevant chunks")
                    for i, chunk in enumerate(relevant_chunks):
                        logger.debug(f"[{request_id}] RAG Chunk {i+1} (Score: {chunk['score']:.4f}):\n{chunk['text']}")
                else:
                    logger.info(f"[{request_id}] ❌ No relevant chunks found")
        except Exception as e:
            logger.error(f"[{request_id}] RAG retrieval failed: {str(e)}")

        # Construct prompt with context
        prompt_text = current_text
        if full_document_context:
            prompt_text = full_document_context + "\n\n" + prompt_text
        if rag_context:
            prompt_text = rag_context + "\n\n" + prompt_text

        # Prepare messages for LLM
        messages = [
            {
                "role": "system",
                "content": CompletionPrompts.SYSTEM_TEMPLATE.format(
                    language=language,
                    streaming_guide=""  # No streaming guide for non-streaming completions
                )
            },
            {
                "role": "user",
                "content": CompletionPrompts.USER_TEMPLATE.format(
                    streaming_note="",
                    text=prompt_text
                )
            }
        ]

        # Log LLM input
        logger.info(f"[{request_id}] LLM Input:")
        for msg in messages:
            logger.info(f"[{request_id}] [{msg['role'].upper()}] {msg['content'][:100]}...")

        # Generate completion with detailed tracking
        llm_model = get_llm()
        result_tokens = []
        
        logger.info(f"[{request_id}] Starting completion generation")
        for chunk in llm_model.create_chat_completion(
            messages=messages,
            max_tokens=config.MAX_NEW_TOKENS,
            temperature=config.TEMPERATURE,
            stream=True,
            request_id=request_id
        ):
            if chunk and "choices" in chunk and chunk["choices"]:
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    # Log every individual token for detailed tracking
                    token_index = len(result_tokens) + 1
                    logger.debug(f"[{request_id}] Token {token_index}: '{content}'")
                    logger.debug(f"[{request_id}] Token {token_index} (hex): {content.encode().hex()}")
                    result_tokens.append(content)

        completion = "".join(result_tokens)
        logger.info(f"[{request_id}] Completion generated ({len(completion)} chars)")
        # Log full completion in chunks to avoid truncation
        if len(completion) > 0:
            logger.info(f"[{request_id}] ===== FULL COMPLETION START =====")
            for i in range(0, len(completion), 500):
                logger.info(f"[{request_id}] {completion[i:i+500]}")
            logger.info(f"[{request_id}] ===== FULL COMPLETION END =====")
        return completion
        
    except Exception as e:
        logger.error(f"[{request_id}] Completion error: {str(e)}", exc_info=True)
        return f"[Error: {str(e)}]"
    finally:
        if close_db and db:
            db.close()