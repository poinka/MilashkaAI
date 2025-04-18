import spacy
from spacy.language import Language
import logging
from typing import List, Dict, Any
import numpy as np
from kuzu import Database
from app.core.models import get_embedding_pipeline
from app.core.config import settings


# Constants for schema
DOCUMENT_TABLE = "Document"
CHUNK_TABLE = "Chunk"
ENTITY_TABLE = "Entity"
CONTAINS_RELATIONSHIP = "Contains"
MENTIONS_RELATIONSHIP = "Mentions"

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


async def build_rag_graph_from_text(doc_id: str, filename: str, text: str):
    """Builds a graph in KuzuDB with nodes and relationships."""
    logging.info(f"Starting RAG graph build for doc_id: {doc_id}")
    
    try:
        db = get_db_connection()
        embedding_pipeline = get_embedding_pipeline()

        # Create schema if not exists
        db.query(f"""
            CREATE NODE TABLE IF NOT EXISTS {DOCUMENT_TABLE} (
                doc_id STRING PRIMARY KEY,
                filename STRING,
                processed_at TIMESTAMP
            )
        """)

        db.query(f"""
            CREATE NODE TABLE IF NOT EXISTS {CHUNK_TABLE} (
                chunk_id STRING PRIMARY KEY,
                doc_id STRING,
                text STRING,
                embedding FLOAT[{settings.VECTOR_DIMENSION}]
            )
        """)

        db.query(f"""
            CREATE REL TABLE IF NOT EXISTS {CONTAINS_RELATIONSHIP} (
                FROM {DOCUMENT_TABLE} TO {CHUNK_TABLE}
            )
        """)

        # Insert document
        db.query(f"""
            INSERT INTO {DOCUMENT_TABLE} (doc_id, filename, processed_at)
            VALUES ($1, $2, CURRENT_TIMESTAMP)
        """, [doc_id, filename])

        # Process chunks and embeddings
        text_chunks = chunk_text(text)
        embeddings = embedding_pipeline.encode(text_chunks, batch_size=32)

        # Insert chunks
        for i, (chunk_text, embedding) in enumerate(zip(text_chunks, embeddings)):
            chunk_id = f"{doc_id}_chunk_{i}"
            
            # Insert chunk
            db.query(f"""
                INSERT INTO {CHUNK_TABLE} (chunk_id, doc_id, text, embedding)
                VALUES ($1, $2, $3, $4)
            """, [chunk_id, doc_id, chunk_text, embedding.tolist()])

            # Create relationship
            db.query(f"""
                MATCH (d:{DOCUMENT_TABLE}), (c:{CHUNK_TABLE})
                WHERE d.doc_id = $1 AND c.chunk_id = $2
                CREATE (d)-[:{CONTAINS_RELATIONSHIP}]->(c)
            """, [doc_id, chunk_id])

        logging.info(f"Successfully built RAG graph for doc_id: {doc_id}")

    except Exception as e:
        logging.error(f"Error building RAG graph: {e}", exc_info=True)
        raise

async def reindex_document(doc_id: str, db=None):
    """
    Reindex a specific document: re-extracts text and updates KuzuDB graph.
    """
    import logging
    from app.core.processing import extract_text_from_file
    from app.db.kuzudb_client import get_db_connection
    from fastapi import HTTPException
    import os

    if db is None:
        db = get_db_connection()

    # Find the uploaded file
    uploads_dir = os.getenv("UPLOADS_DIR", "/uploads")
    file_path = os.path.join(uploads_dir, f"{doc_id}")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File for doc_id {doc_id} not found.")

    try:
        # Delete existing document and its chunks
        db.query(f"""
            MATCH (d:Document {{doc_id: $1}})
            OPTIONAL MATCH (d)-[:Contains]->(c:Chunk)
            DETACH DELETE d, c
        """, [doc_id])

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
        result = db.query(f"""
            MATCH (d:Document {{doc_id: $1}})-[:Contains]->(c:Chunk)
            RETURN count(c) as chunk_count
        """, [doc_id])
        chunks_count = result[0][0] if result else 0

        return {"chunks_indexed": chunks_count}

    except Exception as e:
        logging.error(f"Error reindexing document {doc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))