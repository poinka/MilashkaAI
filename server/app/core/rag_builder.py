import spacy
from spacy.language import Language
import logging
from typing import List, Dict, Any
import numpy as np
from kuzu import Database
from app.core.models import get_embedding_pipeline
from app.core.config import settings
from app.db.kuzudb_client import get_db, KuzuDBClient
from fastapi import Depends, HTTPException
import asyncio
from datetime import datetime
import os

# Constants for schema
DOCUMENT_TABLE = "Document"
CHUNK_TABLE = "Chunk"
CONTAINS_RELATIONSHIP = "Contains"

# Global variable for SpaCy model (load once)
# Consider loading this within the main app lifespan or using dependency injection
nlp: Language | None = None

def load_spacy_model():
    """Loads the SpaCy model with layout parser."""
    global nlp
    if nlp is None:
        try:
            # Load a suitable SpaCy model (multilingual or specific like Russian/English)
            # Example: "xx_ent_wiki_sm" for multilingual entities
            # Example: "ru_core_news_sm" for Russian
            # Example: "en_core_web_sm" for English
            # Choose one appropriate for your primary documentation language or use multiple
            model_name = "en_core_web_sm" # CHANGE if needed
            nlp = spacy.load(model_name)
            # Add the layout parser component if spacy-layout is installed
            # Check if 'layout_parser' pipe already exists or add it
            if "layout_parser" not in nlp.pipe_names:
                try:
                    # The component name might vary based on spacy-layout version
                    nlp.add_pipe("layout_parser") # Or the specific name provided by the lib
                    logging.info("Added spacy-layout parser to SpaCy pipeline.")
                except Exception as e:
                     logging.warning(f"Could not add spacy-layout parser. Layout-based chunking disabled. Error: {e}")
            else:
                 logging.info("spacy-layout parser already in SpaCy pipeline.")

            logging.info(f"SpaCy model '{model_name}' loaded successfully.")
        except OSError:
            logging.error(f"SpaCy model '{model_name}' not found. Download it: python -m spacy download {model_name}")
            raise
        except Exception as e:
            logging.error(f"Error loading SpaCy model or layout parser: {e}", exc_info=True)
            raise

# Ensure SpaCy model is loaded on module import or app startup
load_spacy_model()

def chunk_text(text: str, strategy: str = "paragraph", max_chunk_size: int = 512) -> List[str]:
    """
    Splits text into chunks based on the chosen strategy.
    Strategies: 'paragraph', 'layout', 'fixed'.
    """
    if not nlp:
        logging.warning("SpaCy model not loaded, falling back to simple paragraph splitting.")
        strategy = "paragraph" # Fallback if NLP model failed

    chunks = []
    if strategy == "layout" and "layout_parser" in nlp.pipe_names:
        doc = nlp(text)
        # Access layout elements (e.g., paragraphs, sections - depends on spacy-layout API)
        # This is a placeholder - consult spacy-layout documentation for actual usage
        # Example: Assuming doc._.layout.paragraphs exists
        if hasattr(doc._, 'layout') and hasattr(doc._.layout, 'paragraphs'):
             chunks = [p.text for p in doc._.layout.paragraphs if p.text.strip()]
             logging.info(f"Chunked text using spacy-layout: {len(chunks)} chunks.")
        else:
            logging.warning("spacy-layout attributes not found, falling back to paragraph splitting.")
            strategy = "paragraph" # Fallback if layout attributes missing

    if strategy == "paragraph" or not chunks: # Fallback or explicit choice
        # Simple split by double newline, often indicating paragraphs
        raw_chunks = text.split('\\n\\n')
        chunks = [c.strip() for c in raw_chunks if c.strip()]
        logging.info(f"Chunked text by paragraph: {len(chunks)} chunks.")

    if strategy == "fixed":
        # Split by tokens using SpaCy tokenizer if available
        if nlp:
            doc = nlp(text)
            tokens = [token.text for token in doc]
            chunks = [' '.join(tokens[i:i + max_chunk_size]) for i in range(0, len(tokens), max_chunk_size)]
        else: # Fallback to character-based fixed size if no tokenizer
             chunks = [text[i:i + max_chunk_size*5] for i in range(0, len(text), max_chunk_size*5)] # Approx chars
        logging.info(f"Chunked text by fixed size: {len(chunks)} chunks.")


    # Further refine chunks: ensure they are not too small or too large if needed
    final_chunks = [chunk for chunk in chunks if len(chunk.split()) > 5] # Min 5 words
    logging.info(f"Filtered chunks (min length): {len(final_chunks)} chunks.")
    return final_chunks

async def build_rag_graph_from_text(
    doc_id: str,
    filename: str,
    text: str,
    db: KuzuDBClient = None
):
    logging.info(f"Starting RAG graph build for doc_id: {doc_id}")
    try:
        if db is None:
            db = KuzuDBClient(settings.KUZUDB_PATH)
            db.connect()
            close_db = True
        else:
            close_db = False
        conn = db
        embedding_pipeline = get_embedding_pipeline()
        # Table DDLs are now handled in KuzuDBClient.connect()

        now = datetime.now().isoformat()
        # Ensure the document node exists or create it
        # Use MERGE to avoid race conditions if multiple processes try to create
        conn.execute(f"""
            MERGE (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
            ON CREATE SET d.filename = $filename, d.processed_at = $processed_at, d.status = $status, d.created_at = $created_at, d.updated_at = $updated_at
            ON MATCH SET d.filename = $filename, d.processed_at = $processed_at, d.status = $status, d.updated_at = $updated_at
        """, {
            "doc_id": doc_id, "filename": filename, "processed_at": now,
            "status": "processing", "created_at": now, "updated_at": now # Initial status is processing
        })

        text_chunks = chunk_text(text)
        embeddings = embedding_pipeline.encode(text_chunks, batch_size=32)
        requirements = []
        entities = []
        doc = nlp(text)
        for sent in doc.sents:
            if any(token.lemma_ in ["require", "must", "shall"] for token in sent):
                req_id = f"req_{doc_id}_{len(requirements)}"
                req_type = "functional" if "function" in sent.text.lower() else "non-functional"
                requirements.append({"req_id": req_id, "type": req_type, "description": sent.text})
            for ent in sent.ents:
                entities.append({"entity_id": f"ent_{doc_id}_{len(entities)}",
                               "type": ent.label_.lower(), "name": ent.text})
        for i, (chunked_text, embedding) in enumerate(zip(text_chunks, embeddings)):
            chunk_id = f"{doc_id}_chunk_{i}"
            conn.execute(f"""
                CREATE (c:{CHUNK_TABLE} {{chunk_id: $chunk_id, doc_id: $doc_id,
                    text: $text, embedding: $embedding}})
            """, {
                "chunk_id": chunk_id, "doc_id": doc_id, "text": chunked_text,
                "embedding": embedding.tolist()
            })
            conn.execute(f"""
                MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}}),
                      (c:{CHUNK_TABLE} {{chunk_id: $chunk_id}})
                CREATE (d)-[:{CONTAINS_RELATIONSHIP}]->(c)
            """, {"doc_id": doc_id, "chunk_id": chunk_id})
            for req in requirements:
                if req["description"] in chunked_text:
                    conn.execute("""
                        MATCH (r:Requirement {req_id: $req_id}),
                              (c:Chunk {chunk_id: $chunk_id})
                        CREATE (r)-[:DescribedBy]->(c)
                    """, {"req_id": req["req_id"], "chunk_id": chunk_id})
        for req in requirements:
            conn.execute("""
                CREATE (r:Requirement {req_id: $req_id, type: $type,
                    description: $description, created_at: $created_at})
            """, {
                "req_id": req["req_id"], "type": req["type"],
                "description": req["description"], "created_at": now
            })
            conn.execute("""
                MATCH (r:Requirement {req_id: $req_id}),
                      (d:Document {doc_id: $doc_id})
                CREATE (r)-[:References]->(d)
            """, {"req_id": req["req_id"], "doc_id": doc_id})
        for ent in entities:
            conn.execute("""
                CREATE (e:Entity {entity_id: $entity_id, type: $type, name: $name})
            """, {
                "entity_id": ent["entity_id"], "type": ent["type"], "name": ent["name"]
            })
            for req in requirements:
                if ent["name"].lower() in req["description"].lower():
                    conn.execute("""
                        MATCH (r:Requirement {req_id: $req_id}),
                              (e:Entity {entity_id: $entity_id})
                        CREATE (r)-[:Implements]->(e)
                    """, {"req_id": req["req_id"], "entity_id": ent["entity_id"]})
        logging.info(f"Built RAG graph with {len(requirements)} requirements for doc_id: {doc_id}")
    except Exception as e:
        logging.error(f"Error building RAG graph: {e}", exc_info=True)
        # Update status to error in DB
        try:
            if db is not None:
                now = datetime.now().isoformat()
                db.execute(f"""
                    MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
                    SET d.status = 'error', d.updated_at = $updated_at, d.error = $error_msg
                """, {"doc_id": doc_id, "updated_at": now, "error_msg": str(e)})
        except Exception as db_err:
            logging.error(f"Failed to update document status to error: {db_err}")
        raise
    finally:
        if 'close_db' in locals() and close_db:
            db.close()


async def reindex_document(
    doc_id: str,
    db: KuzuDBClient = Depends(get_db)
):
    """
    Reindex a specific document: re-extracts text and updates KuzuDB graph.
    """
    from app.core.processing import extract_text_from_file

    conn = db

    # Find the uploaded file
    # Use settings for uploads path
    uploads_dir = settings.UPLOADS_PATH 
    # Find the file by doc_id, trying common extensions
    original_filename = None
    try:
        res = conn.execute(f"MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}}) RETURN d.filename", {"doc_id": doc_id})
        if res.has_next():
            original_filename = res.get_next()[0]
    except Exception as e:
        logging.warning(f"Could not retrieve original filename for {doc_id}: {e}")

    file_path = None
    if original_filename:
        base_path = os.path.join(uploads_dir, doc_id)
        ext = os.path.splitext(original_filename)[1]
        potential_path = f"{base_path}{ext}"
        if os.path.exists(potential_path):
            file_path = potential_path
        else: 
             logging.warning(f"File with original extension not found at {potential_path}")
             # Fallback: Check without extension or common ones if needed
             if os.path.exists(base_path):
                 file_path = base_path # Maybe saved without extension?
                 logging.warning(f"Found file without extension at {base_path}")

    if not file_path:
         # Last resort: try globbing if filename wasn't found/retrieved
        possible_files = [f for f in os.listdir(uploads_dir) if f.startswith(doc_id)]
        if possible_files:
            file_path = os.path.join(uploads_dir, possible_files[0])
            logging.warning(f"Found file via globbing: {file_path}")
        else:
            raise HTTPException(status_code=404, detail=f"File for doc_id {doc_id} not found in {uploads_dir}.")

    try:
        # Delete existing document and its chunks/relationships
        conn.execute(f"""
            MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
            OPTIONAL MATCH (d)-[r]-()
            DETACH DELETE d
        """, {"doc_id": doc_id})
        logging.info(f"Deleted existing data for doc_id {doc_id} before reindexing.")

        # Simulate UploadFile for extract_text_from_file
        class DummyUploadFile:
            def __init__(self, filepath):
                self.filename = os.path.basename(filepath)
                self._file = open(filepath, "rb")
                # Determine content type if possible, otherwise default
                import mimetypes
                self.content_type, _ = mimetypes.guess_type(filepath)
                if not self.content_type:
                    self.content_type = "application/octet-stream"

            async def read(self):
                return self._file.read()

            async def seek(self, pos):
                self._file.seek(pos)
                
            async def close(self):
                self._file.close()

        # Extract text and rebuild graph
        upload_file = DummyUploadFile(file_path)
        try:
            text = await extract_text_from_file(upload_file)
            if not text or text.isspace():
                 logging.warning(f"No text extracted during reindex for {doc_id}")
                 # Create a minimal document entry with error status
                 now = datetime.now().isoformat()
                 conn.execute(f"""
                    MERGE (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
                    ON CREATE SET d.filename = $filename, d.status = 'error', d.error = 'No text content found', d.created_at = $now, d.updated_at = $now
                    ON MATCH SET d.filename = $filename, d.status = 'error', d.error = 'No text content found', d.updated_at = $now
                 """, {"doc_id": doc_id, "filename": upload_file.filename, "now": now})
                 return {"chunks_indexed": 0, "status": "error", "detail": "No text content found"}
            
            # Pass the db connection explicitly
            await build_rag_graph_from_text(doc_id, upload_file.filename, text, db=conn) 
        finally:
            await upload_file.close()

        # Count chunks to confirm indexing
        result = conn.execute(f"""
            MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})-[:{CONTAINS_RELATIONSHIP}]->(c:{CHUNK_TABLE})
            RETURN count(c) as chunk_count
        """, {"doc_id": doc_id})
        chunks_count = result.get_next()[0] if result.has_next() else 0
        logging.info(f"Reindexing for doc_id {doc_id} completed. Indexed {chunks_count} chunks.")

        return {"chunks_indexed": chunks_count, "status": "indexed"}

    except Exception as e:
        logging.error(f"Error reindexing document {doc_id}: {e}", exc_info=True)
        # Attempt to update status to error
        try:
            now = datetime.now().isoformat()
            conn.execute(f"""
                MERGE (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
                ON CREATE SET d.status = 'error', d.error = $error_msg, d.created_at = $now, d.updated_at = $now
                ON MATCH SET d.status = 'error', d.error = $error_msg, d.updated_at = $now
            """, {"doc_id": doc_id, "error_msg": str(e), "now": now})
        except Exception as db_err:
            logging.error(f"Failed to update document status to error during reindex exception handling: {db_err}")
        raise HTTPException(status_code=500, detail=str(e))