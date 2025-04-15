import spacy
from spacy.language import Language
import logging
from typing import List, Dict, Any
import numpy as np

# Import necessary components from the project
from app.db.falkordb_client import get_db_connection
from app.core.models import get_embedding_pipeline # Accessor for embedding model

# Constants for graph schema
DOC_LABEL = "Document"
CHUNK_LABEL = "Chunk"
ENTITY_LABEL = "Entity" # Example: Requirement, Actor, Concept
CONTAINS_REL = "CONTAINS"
MENTIONS_REL = "MENTIONS"
RELATED_TO_REL = "RELATED_TO" # Generic relationship

# Global constants for RAG index
GLOBAL_INDEX_NAME = "milashka_chunk_embedding_idx"
VECTOR_FIELD_NAME = "embedding"

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


async def build_rag_graph_from_text(doc_id: str, filename: str, text: str):
    """
    Processes extracted text, builds a graph in FalkorDB with nodes,
    relationships, and vector embeddings, adding chunks to a global index.
    """
    logging.info(f"Starting RAG graph build for doc_id: {doc_id}")
    if not nlp:
        raise RuntimeError("SpaCy model not loaded. Cannot process text.")

    try:
        db = get_db_connection()
        embedding_pipeline = get_embedding_pipeline()
        # Graph name specific to the document
        graph_name = f"doc_{doc_id}"
        graph = db.select_graph(graph_name)

        # 1. Create Document Node
        doc_props = {"doc_id": doc_id, "filename": filename, "processed_at": "$timestamp"}
        graph.query(f"MERGE (d:{DOC_LABEL} {{doc_id: $doc_id}}) SET d = $props",
                    params={"doc_id": doc_id, "props": doc_props})
        logging.info(f"Created/Updated Document node for {doc_id}")

        # 2. Chunk Text
        # Choose chunking strategy (e.g., 'layout' if available, else 'paragraph')
        chunking_strategy = "layout" if "layout_parser" in nlp.pipe_names else "paragraph"
        text_chunks = chunk_text(text, strategy=chunking_strategy)

        if not text_chunks:
            logging.warning(f"No text chunks generated for document {doc_id}. Skipping chunk processing.")
            return

        # 3. Process Chunks (Nodes, Embeddings, Relationships)
        chunk_ids = []
        chunk_texts = []
        chunk_embeddings = []

        logging.info(f"Generating embeddings for {len(text_chunks)} chunks...")
        # Generate embeddings in batches if possible (depends on embedding model)
        embeddings = embedding_pipeline.encode(text_chunks, batch_size=32, show_progress_bar=False) # Adjust batch_size
        logging.info("Embeddings generated.")

        # Check embedding dimension (important for index creation)
        if embeddings is None or len(embeddings) == 0:
             raise ValueError("Embedding generation failed or returned empty.")
        embedding_dim = len(embeddings[0])
        logging.info(f"Embedding dimension: {embedding_dim}")

        # Use Cypher UNWIND for potentially faster batch insertion
        chunk_data_list = []
        for i, chunk_text in enumerate(text_chunks):
            chunk_id = f"{doc_id}_chunk_{i}"
            chunk_data = {
                "chunk_id": chunk_id,
                "doc_id": doc_id, # Store doc_id on the chunk node
                "filename": filename, # Store filename on the chunk node
                "text": chunk_text,
                VECTOR_FIELD_NAME: embeddings[i].tolist(), # Use constant
                "chunk_index": i
            }
            chunk_data_list.append(chunk_data)

        logging.info(f"Inserting {len(chunk_data_list)} chunks into graph '{graph_name}'...")
        # Cypher query to create chunks and link them to the document
        query = f"""
        UNWIND $batch as chunk_data
        MATCH (d:{DOC_LABEL} {{doc_id: chunk_data.doc_id}})
        CREATE (c:{CHUNK_LABEL} {{ 
            chunk_id: chunk_data.chunk_id,
            doc_id: chunk_data.doc_id, 
            filename: chunk_data.filename,
            text: chunk_data.text,
            {VECTOR_FIELD_NAME}: chunk_data.{VECTOR_FIELD_NAME},
            index: chunk_data.chunk_index
        }})
        CREATE (d)-[:{CONTAINS_REL}]->(c)
        RETURN count(c) as created_count
        """
        result = graph.query(query, params={"batch": chunk_data_list})
        logging.info(f"Inserted {result.result_set[0][0]} chunks into graph '{graph_name}'.")

        # 4. (Optional) Extract Entities and Relationships
        # This requires more advanced NLP (NER, Relation Extraction)
        # Example using basic SpaCy NER:
        # for i, chunk_node_id in enumerate(chunk_ids):
        #     chunk_doc = nlp(chunk_texts[i])
        #     for ent in chunk_doc.ents:
        #         # Create/Merge Entity node
        #         ent_id = f"{ent.label_}_{ent.text.lower().replace(' ', '_')}"
        #         graph.query(f"MERGE (e:{ENTITY_LABEL} {{entity_id: $ent_id, label: $label, name: $name}})",
        #                     params={"ent_id": ent_id, "label": ent.label_, "name": ent.text})
        #         # Create MENTIONS relationship
        #         graph.query(f"""
        #             MATCH (c:{CHUNK_LABEL} {{chunk_id: $chunk_id}})
        #             MATCH (e:{ENTITY_LABEL} {{entity_id: $ent_id}})
        #             MERGE (c)-[:{MENTIONS_REL}]->(e)
        #         """, params={"chunk_id": chunk_node_id, "ent_id": ent_id})

        # 5. Create Global Vector Index (if it doesn't exist)
        # This index spans across all document graphs that follow the pattern
        logging.info(f"Checking/Creating GLOBAL vector index '{GLOBAL_INDEX_NAME}'...")
        try:
            # Check existing indexes
            indexes = db.execute_command("FT._LIST")
            if GLOBAL_INDEX_NAME not in indexes:
                 # Create index using FT.CREATE
                 # Indexing all graphs matching the pattern `doc_*` for the CHUNK_LABEL
                 # Add TAG fields for filtering
                 create_index_query = (
                     f"FT.CREATE {GLOBAL_INDEX_NAME} ON HASH PREFIX 1 doc_:{CHUNK_LABEL}: " # Index chunks in graphs starting with doc_
                     f"SCHEMA text TEXT WEIGHT 0.5 " # Optional: index text for hybrid search
                     f"doc_id TAG SEPARATOR , " # Index doc_id for filtering
                     f"filename TAG SEPARATOR , " # Index filename for filtering
                     f"{VECTOR_FIELD_NAME} VECTOR HNSW 6 DIM {embedding_dim} TYPE FLOAT32 DISTANCE_METRIC COSINE"
                 )
                 db.execute_command(create_index_query)
                 logging.info(f"Global vector index '{GLOBAL_INDEX_NAME}' created successfully.")
            else:
                 logging.info(f"Global vector index '{GLOBAL_INDEX_NAME}' already exists.")

        except Exception as index_e:
            # Handle specific errors for index creation/checking
            logging.error(f"Failed to create or verify global vector index '{GLOBAL_INDEX_NAME}': {index_e}", exc_info=True)
            raise RuntimeError(f"Failed to setup global vector index: {index_e}") from index_e

        logging.info(f"Successfully built RAG graph components for doc_id: {doc_id}")

    except Exception as e:
        logging.error(f"Error building RAG graph for doc_id {doc_id}: {e}", exc_info=True)
        raise


async def reindex_document(doc_id: str, db=None):
    """
    Reindex a specific document: re-extracts text, rebuilds RAG graph, and updates embeddings.
    """
    import logging
    from app.core.processing import extract_text_from_file
    from app.db.falkordb_client import get_db_connection
    from fastapi import HTTPException
    import os

    if db is None:
        db = get_db_connection()

    # Find the uploaded file for this doc_id
    uploads_dir = os.getenv("UPLOADS_DIR", "/uploads")
    file_path = os.path.join(uploads_dir, f"{doc_id}")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File for doc_id {doc_id} not found.")

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

    upload_file = DummyUploadFile(file_path)
    text = await extract_text_from_file(upload_file)
    await build_rag_graph_from_text(doc_id, os.path.basename(file_path), text)
    # Optionally, count chunks (could be improved)
    return {"chunks_indexed": "unknown"}
