import spacy
from spacy.language import Language
from spacy.matcher import Matcher
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

# Constants for schema (nodes and relationships)
DOCUMENT_TABLE = "Document"
CHUNK_TABLE = "Chunk"
REQUIREMENT_TABLE = "Requirement"
ENTITY_TABLE = "Entity"

CONTAINS_RELATIONSHIP = "Contains"
DESCRIBED_BY_RELATIONSHIP = "DescribedBy"
REFERENCES_RELATIONSHIP = "References"
IMPLEMENTS_RELATIONSHIP = "Implements"

# Global variable for SpaCy model (load once)
nlp: Language | None = None

def load_spacy_model():
    """Loads the SpaCy model with layout parser."""
    global nlp
    if nlp is None:
        try:
            model_name = "en_core_web_sm"  # Change if needed
            nlp = spacy.load(model_name)
            if "layout_parser" not in nlp.pipe_names:
                try:
                    nlp.add_pipe("layout_parser")
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
        strategy = "paragraph"

    chunks = []
    if strategy == "layout" and "layout_parser" in nlp.pipe_names:
        doc = nlp(text)
        if hasattr(doc._, 'layout') and hasattr(doc._.layout, 'paragraphs'):
            chunks = [p.text for p in doc._.layout.paragraphs if p.text.strip()]
            logging.info(f"Chunked text using spacy-layout: {len(chunks)} chunks.")
        else:
            logging.warning("spacy-layout attributes not found, falling back to paragraph splitting.")
            strategy = "paragraph"

    if strategy == "paragraph" or not chunks:
        raw_chunks = text.split('\n')
        chunks = [c.strip() for c in raw_chunks if c.strip()]
        logging.info(f"Chunked text by paragraph: {len(chunks)} chunks.")

    elif strategy == "fixed":
        if nlp:
            doc = nlp(text)
            tokens = [token.text for token in doc]
            chunks = [' '.join(tokens[i:i + max_chunk_size]) for i in range(0, len(tokens), max_chunk_size)]
        else:
            chunks = [text[i:i + max_chunk_size*5] for i in range(0, len(text), max_chunk_size*5)]
        logging.info(f"Chunked text by fixed size: {len(chunks)} chunks.")

    # logging.info(f"Chunks: {chunks}")
    final_chunks = [chunk for chunk in chunks if len(chunk.split()) > 5]
    logging.info(f"Filtered chunks (min length): {len(final_chunks)} chunks.")
    return final_chunks

def extract_requirements(doc: spacy.tokens.Doc, doc_id: str) -> List[Dict[str, Any]]:
    """
    Extracts requirements from a SpaCy Doc object using dependency parsing and rule-based matching.
    Returns a list of requirement dictionaries.
    """
    requirements = []
    matcher = Matcher(doc.vocab)

    # Define system-related subjects and user-related subjects to exclude
    system_subjects = ["system", "api", "login", "process", "application", "module", "service"]
    user_subjects = ["user", "users", "admin", "administrator"]

    # Define a pattern for requirements: System-related subject + Modal verb + Verb
    requirement_pattern = [
        {"LOWER": {"IN": system_subjects}, "DEP": "nsubj"},  # Subject must be system-related
        {"LEMMA": {"IN": ["shall", "must", "should", "need", "require", "obligate", "have"]}, "POS": "VERB"},
        {"POS": "VERB", "OP": "+"},  # At least one verb after the modal
    ]
    matcher.add("REQUIREMENT_PATTERN", [requirement_pattern])

    # Find matches for the pattern
    matches = matcher(doc)
    matched_sentences = set()  # To avoid duplicates

    for match_id, start, end in matches:
        span = doc[start:end]
        # Find the sentence containing this match
        sent = span.sent
        if sent in matched_sentences:
            continue
        matched_sentences.add(sent)

        # Determine requirement type based on keywords
        req_type = "functional" if any(term in sent.text.lower() for term in ["function", "feature", "capability"]) else "non-functional"
        req_id = f"req_{doc_id}_{len(requirements)}"
        requirements.append({
            "req_id": req_id,
            "type": req_type,
            "description": sent.text.strip()
        })
        logging.info(f"Detected requirement: {sent.text}")

    # Additional check using dependency parsing for sentences not caught by the matcher
    for sent in doc.sents:
        if sent in matched_sentences:
            continue

        modal_token = None
        subject_token = None

        # Look for modal verbs and their subjects
        for token in sent:
            if token.lemma_.lower() in ["shall", "must", "should", "need", "require", "obligate", "have"] and token.dep_ in ("aux", "ROOT"):
                modal_token = token
                # Find the subject (nsubj) of the verb that the modal is attached to
                for child in token.head.children:
                    if child.dep_ == "nsubj":
                        subject_token = child
                        break
                break

        if not modal_token or not subject_token:
            continue

        # Check if the subject is system-related
        subject_text = subject_token.text.lower()
        is_system_related = any(subject_text in system_subject for system_subject in system_subjects)

        # Exclude user-related subjects unless the verb indicates a system action
        is_user_related = any(subject_text in user_subject for user_subject in user_subjects)
        if is_user_related:
            # Allow user-related subjects if the verb indicates a system action (e.g., "The user must authenticate")
            verb = modal_token.head.text.lower()
            system_verbs = ["authenticate", "access", "interact", "use"]
            if not any(verb in system_verb for system_verb in system_verbs):
                continue

        if not is_system_related and not (is_user_related and any(verb in system_verb for system_verb in system_verbs)):
            continue

        req_type = "functional" if any(term in sent.text.lower() for term in ["function", "feature", "capability"]) else "non-functional"
        req_id = f"req_{doc_id}_{len(requirements)}"
        requirements.append({
            "req_id": req_id,
            "type": req_type,
            "description": sent.text.strip()
        })
        logging.info(f"Detected requirement (dependency parsing): {sent.text}")

    return requirements
    
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
        now = datetime.now().isoformat()
        
        # Ensure the document node exists or create it
        conn.execute(f"""
            MERGE (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
            ON CREATE SET d.filename = $filename, d.processed_at = $processed_at, d.status = $status, d.created_at = $created_at, d.updated_at = $updated_at
            ON MATCH SET d.filename = $filename, d.processed_at = $processed_at, d.status = $status, d.updated_at = $updated_at
        """, {
            "doc_id": doc_id, "filename": filename, "processed_at": now,
            "status": "processing", "created_at": now, "updated_at": now
        })

        text_chunks = chunk_text(text)
        embeddings = embedding_pipeline.encode(text_chunks, batch_size=32)
        
        doc = nlp(text)

        requirements = extract_requirements(doc, doc_id)
        entities = []

        for sent in doc.sents:
            for ent in sent.ents:
                entities.append({
                    "entity_id": f"ent_{doc_id}_{len(entities)}",
                    "type": ent.label_.lower(),
                    "name": ent.text
                })
        logging.info(f"Extracted {len(requirements)} requirements")

        # Insert chunks and relationships
        for i, (chunked_text, embedding) in enumerate(zip(text_chunks, embeddings)):
            chunk_id = f"{doc_id}_chunk_{i}"
            # Use a consistent schema without created_at field for chunks
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
                    conn.execute(f"""
                        MATCH (r:{REQUIREMENT_TABLE} {{req_id: $req_id}}),
                              (c:{CHUNK_TABLE} {{chunk_id: $chunk_id}})
                        CREATE (r)-[:{DESCRIBED_BY_RELATIONSHIP}]->(c)
                    """, {"req_id": req["req_id"], "chunk_id": chunk_id})
        for req in requirements:
            conn.execute(f"""
                CREATE (r:{REQUIREMENT_TABLE} {{req_id: $req_id, type: $type,
                    description: $description, created_at: $created_at}})
            """, {
                "req_id": req["req_id"], "type": req["type"],
                "description": req["description"], "created_at": now
            })
            conn.execute(f"""
                MATCH (r:{REQUIREMENT_TABLE} {{req_id: $req_id}}),
                      (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
                CREATE (r)-[:{REFERENCES_RELATIONSHIP}]->(d)
            """, {"req_id": req["req_id"], "doc_id": doc_id})
        for ent in entities:
            conn.execute(f"""
                CREATE (e:{ENTITY_TABLE} {{entity_id: $entity_id, type: $type, name: $name}})
            """, {
                "entity_id": ent["entity_id"], "type": ent["type"], "name": ent["name"]
            })
            for req in requirements:
                if ent["name"].lower() in req["description"].lower():
                    conn.execute(f"""
                        MATCH (r:{REQUIREMENT_TABLE} {{req_id: $req_id}}),
                              (e:{ENTITY_TABLE} {{entity_id: $entity_id}})
                        CREATE (r)-[:{IMPLEMENTS_RELATIONSHIP}]->(e)
                    """, {"req_id": req["req_id"], "entity_id": ent["entity_id"]})

        # Update document status to "indexed" after all processing is complete
        now = datetime.now().isoformat()  # Refresh timestamp
        conn.execute(f"""
            MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
            SET d.status = 'indexed', d.updated_at = $updated_at
        """, {
            "doc_id": doc_id,
            "updated_at": now
        })
        
        logging.info(f"Built RAG graph with {len(requirements)} requirements for doc_id: {doc_id}")
    except Exception as e:
        logging.error(f"Error building RAG graph: {e}", exc_info=True)
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

async def fetch_requirements(
    doc_id: str | None = None,
    req_type: str | None = None,
    db: KuzuDBClient = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Fetches requirements from the database with associated chunks and entities.
    
    Args:
        doc_id (str, optional): Filter by document ID. If None, fetch requirements from all documents.
        req_type (str, optional): Filter by requirement type (e.g., 'functional', 'non-functional').
        db (KuzuDBClient): Database client dependency.
    
    Returns:
        List of dictionaries containing requirement details, associated chunks, and entities.
    """
    conn = db
    query = f"""
        MATCH (r:{REQUIREMENT_TABLE})
        OPTIONAL MATCH (r)-[:{REFERENCES_RELATIONSHIP}]->(d:{DOCUMENT_TABLE})
        OPTIONAL MATCH (r)-[:{DESCRIBED_BY_RELATIONSHIP}]->(c:{CHUNK_TABLE})
        OPTIONAL MATCH (r)-[:{IMPLEMENTS_RELATIONSHIP}]->(e:{ENTITY_TABLE})
    """
    conditions = []
    params = {}

    # Filter by doc_id if provided
    if doc_id:
        conditions.append("d.doc_id = $doc_id")
        params["doc_id"] = doc_id

    # Filter by requirement type if provided
    if req_type:
        conditions.append("r.type = $req_type")
        params["req_type"] = req_type

    # Add WHERE clause if there are conditions
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    # Return results
    query += f"""
        RETURN r.req_id, r.type, r.description, r.created_at,
               collect(c.text) as chunks,
               collect(e.name) as entities,
               d.doc_id as document_id
        ORDER BY r.created_at DESC
    """

    result = conn.execute(query, params)
    requirements = []
    while result.has_next():
        row = result.get_next()
        requirements.append({
            "req_id": row[0],
            "type": row[1],
            "description": row[2],
            "created_at": row[3],
            "chunks": row[4] if row[4] else [],  # List of associated chunk texts
            "entities": row[5] if row[5] else [],  # List of associated entity names
            "document_id": row[6]
        })

    return requirements


async def reindex_document(
    doc_id: str,
    db: KuzuDBClient = Depends(get_db)
):
    """
    Reindex a specific document: re-extracts text and updates KuzuDB graph.
    """
    from app.core.processing import extract_text_from_file

    conn = db

    uploads_dir = settings.UPLOADS_PATH 
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
            if os.path.exists(base_path):
                file_path = base_path
                logging.warning(f"Found file without extension at {base_path}")

    if not file_path:
        possible_files = [f for f in os.listdir(uploads_dir) if f.startswith(doc_id)]
        if possible_files:
            file_path = os.path.join(uploads_dir, possible_files[0])
            logging.warning(f"Found file via globbing: {file_path}")
        else:
            raise HTTPException(status_code=404, detail=f"File for doc_id {doc_id} not found in {uploads_dir}.")

    try:
        conn.execute(f"""
            MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
            OPTIONAL MATCH (d)-[r]-()
            DETACH DELETE d
        """, {"doc_id": doc_id})
        logging.info(f"Deleted existing data for doc_id {doc_id} before reindexing.")

        class DummyUploadFile:
            def __init__(self, filepath):
                self.filename = os.path.basename(filepath)
                self._file = open(filepath, "rb")
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

        upload_file = DummyUploadFile(file_path)
        try:
            text = await extract_text_from_file(upload_file)
            if not text or text.isspace():
                logging.warning(f"No text extracted during reindex for {doc_id}")
                now = datetime.now().isoformat()
                conn.execute(f"""
                    MERGE (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
                    ON CREATE SET d.filename = $filename, d.status = 'error', d.error = 'No text content found', d.created_at = $now, d.updated_at = $now
                    ON MATCH SET d.filename = $filename, d.status = 'error', d.error = 'No text content found', d.updated_at = $now
                """, {"doc_id": doc_id, "filename": upload_file.filename, "now": now})
                return {"chunks_indexed": 0, "status": "error", "detail": "No text content found"}
            
            await build_rag_graph_from_text(doc_id, upload_file.filename, text, db=conn) 
        finally:
            await upload_file.close()

        result = conn.execute(f"""
            MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})-[:{CONTAINS_RELATIONSHIP}]->(c:{CHUNK_TABLE})
            RETURN count(c) as chunk_count
        """, {"doc_id": doc_id})
        chunks_count = result.get_next()[0] if result.has_next() else 0
        logging.info(f"Reindexing for doc_id {doc_id} completed. Indexed {chunks_count} chunks.")

        return {"chunks_indexed": chunks_count, "status": "indexed"}

    except Exception as e:
        logging.error(f"Error reindexing document {doc_id}: {e}", exc_info=True)
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