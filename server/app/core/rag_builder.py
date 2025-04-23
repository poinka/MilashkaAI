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
        # Table DDLs
        create_document_table = f"""
        CREATE NODE TABLE IF NOT EXISTS {DOCUMENT_TABLE} (
            doc_id STRING, filename STRING, processed_at STRING, status STRING,
            created_at STRING, updated_at STRING, PRIMARY KEY (doc_id)
        )"""
        create_chunk_table = f"""
        CREATE NODE TABLE IF NOT EXISTS {CHUNK_TABLE} (
            chunk_id STRING,
            doc_id STRING,
            text STRING,
            embedding FLOAT[],
            PRIMARY KEY (chunk_id)
        )"""
        create_contains_rel = f"""
        CREATE REL TABLE IF NOT EXISTS {CONTAINS_RELATIONSHIP} (
            FROM {DOCUMENT_TABLE} TO {CHUNK_TABLE}
        )"""
        create_requirement_table = """
        CREATE NODE TABLE IF NOT EXISTS Requirement (
            req_id STRING, type STRING, description STRING, created_at STRING,
            PRIMARY KEY (req_id)
        )"""
        create_entity_table = """
        CREATE NODE TABLE IF NOT EXISTS Entity (
            entity_id STRING, type STRING, name STRING, PRIMARY KEY (entity_id)
        )"""
        create_implements_rel = """
        CREATE REL TABLE IF NOT EXISTS Implements (
            FROM Requirement TO Entity
        )"""
        create_described_by_rel = """
        CREATE REL TABLE IF NOT EXISTS DescribedBy (
            FROM Requirement TO Chunk
        )"""
        create_references_rel = """
        CREATE REL TABLE IF NOT EXISTS References (
            FROM Requirement TO Document
        )"""
        for query in [create_document_table, create_chunk_table, create_contains_rel,
                      create_requirement_table, create_entity_table,
                      create_implements_rel, create_described_by_rel, create_references_rel]:
            conn.execute(query)
        now = datetime.now().isoformat()
        conn.execute(f"""
            CREATE (d:{DOCUMENT_TABLE} {{doc_id: $doc_id, filename: $filename,
                processed_at: $processed_at, status: $status,
                created_at: $created_at, updated_at: $updated_at}})
        """, {
            "doc_id": doc_id, "filename": filename, "processed_at": now,
            "status": "indexed", "created_at": now, "updated_at": now
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
    uploads_dir = os.getenv("UPLOADS_DIR", settings.UPLOADS_PATH)
    file_path = os.path.join(uploads_dir, f"{doc_id}")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File for doc_id {doc_id} not found.")

    try:
        # Delete existing document and its chunks
        conn.execute(f"""
            MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
            OPTIONAL MATCH (d)-[:{CONTAINS_RELATIONSHIP}]->(c:{CHUNK_TABLE})
            DETACH DELETE d, c
        """, {"doc_id": doc_id})

        # Simulate UploadFile for extract_text_from_file
        class DummyUploadFile:
            def __init__(self, filename):
                self.filename = filename
                self.file = open(filename, "rb")
                self.content_type = None
            async def read(self):
                return self.file.read()
            async def seek(self, pos):
                self.file.seek(pos)

        # Extract text and rebuild graph
        upload_file = DummyUploadFile(file_path)
        text = await extract_text_from_file(upload_file)
        await build_rag_graph_from_text(doc_id, os.path.basename(file_path), text)

        # Count chunks
        result = conn.execute(f"""
            MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})-[:{CONTAINS_RELATIONSHIP}]->(c:{CHUNK_TABLE})
            RETURN count(c) as chunk_count
        """, {"doc_id": doc_id})
        chunks_count = result.get_next()[0] if result.has_next() else 0

        return {"chunks_indexed": chunks_count}

    except Exception as e:
        logging.error(f"Error reindexing document {doc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))