import spacy
from spacy.language import Language
from spacy.matcher import Matcher
import logging
from typing import List, Dict, Any
import numpy as np
from kuzu import Database
from app.core.models import get_embedding_pipeline
from app.core.spacy_components import setup_spacy_extensions
from app.core.config import settings
from app.db.kuzudb_client import get_db, KuzuDBClient
from fastapi import Depends, HTTPException
import asyncio
from datetime import datetime
import os
import re
from langdetect import detect, LangDetectException

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.FileHandler('/app/requirements.log'), logging.StreamHandler()]
)

# Constants for schema
DOCUMENT_TABLE = "Document"
CHUNK_TABLE = "Chunk"
REQUIREMENT_TABLE = "Requirement"
ENTITY_TABLE = "Entity"
ACTOR_TABLE = "Actor"
ACTION_TABLE = "Action"
OBJECT_TABLE = "Object"
RESULT_TABLE = "Result"
PROJECT_ENTITY_TABLE = "ProjectEntity"
USER_INTERACTION_TABLE = "UserInteraction"

CONTAINS_RELATIONSHIP = "Contains"
DESCRIBED_BY_RELATIONSHIP = "DescribedBy"
REFERENCES_RELATIONSHIP = "References"
IMPLEMENTS_RELATIONSHIP = "Implements"
PERFORMS_RELATIONSHIP = "Performs"
COMMITS_RELATIONSHIP = "Commits"
ON_WHAT_PERFORMED_RELATIONSHIP = "On_what_performed"
EXPECTS_RELATIONSHIP = "Expects"
DEPENDS_ON_RELATIONSHIP = "Depends_on"
RELATES_TO_RELATIONSHIP = "Relates_to"
DESCRIBED_IN_RELATIONSHIP = "Described_in"
LINKED_TO_FEEDBACK_RELATIONSHIP = "Linked_to_feedback"

# Global variables for SpaCy models
nlp: Language | None = None
nlp_ru: Language | None = None
nlp_en: Language | None = None

def load_spacy_model():
    """Loads SpaCy models for Russian and English with layout parser."""
    global nlp_ru, nlp_en, nlp
    nlp_ru = None
    nlp_en = None
    nlp = None
    try:
        setup_spacy_extensions()
        nlp_en = spacy.load("en_core_web_lg")  # Upgraded to large model for better NER and parsing
        if "layout_parser" not in nlp_en.pipe_names:
            nlp_en.add_pipe("layout_parser", last=True)
        logging.info("Loaded English SpaCy model 'en_core_web_lg'")
        nlp_ru = spacy.load("ru_core_news_lg")
        if "layout_parser" not in nlp_ru.pipe_names:
            nlp_ru.add_pipe("layout_parser", last=True)
        logging.info("Loaded Russian SpaCy model 'ru_core_news_lg'")
    except Exception as e:
        logging.error(f"Error loading SpaCy models: {e}", exc_info=True)
        raise

load_spacy_model()

def is_requirement_sentence(sent: spacy.tokens.Span, lang: str) -> bool:
    """Checks if a sentence likely contains a requirement based on modal verbs or structure."""
    if lang == 'en':
        modal_verbs = ["shall", "must", "should", "will", "need", "require", "obligate", "have"]
    else:  # Russian
        modal_verbs = ["должен", "должна", "должно", "следует", "нужно", "обязан", "требуется"]
    
    for token in sent:
        if token.lemma_.lower() in modal_verbs and token.pos_ == "VERB":
            return True
    return False

def chunk_text(text: str, strategy: str = "layout", max_chunk_size: int = 512) -> List[tuple[str, int, int, str]]:
    """Splits text into chunks with type and position info, preserving requirement context."""
    global nlp
    if not nlp:
        logging.warning("SpaCy model not loaded, falling back to paragraph splitting.")
        strategy = "paragraph"

    chunks = []
    is_pdf = text.endswith('.pdf') and os.path.exists(text)

    if is_pdf:
        doc = nlp(text)
        if hasattr(doc._, 'elements') and doc._.elements:
            for e in doc._.elements:
                chunk_text = e['text'].strip()
                if not chunk_text:
                    continue
                chunk_type = ('list_item' if e['type'] == 'list_item' else
                              'header' if re.match(r'^\d+\.\s+[A-Z][A-Za-z\s]+', chunk_text) else
                              'paragraph')
                start = e.get('start', text.find(chunk_text))
                end = start + len(chunk_text)
                chunks.append((chunk_text, start, end, chunk_type))
        else:
            text = doc.text
            strategy = "paragraph"
    else:
        doc = nlp(text)
        if strategy == "layout" and "layout_parser" in nlp.pipe_names and hasattr(doc._, 'elements') and doc._.elements:
            for e in doc._.elements:
                chunk_text = e['text'].strip()
                if not chunk_text:
                    continue
                chunk_type = ('list_item' if e['type'] == 'list_item' or re.match(r'^\d+\.\s|^[\|\*\-]\s', chunk_text) else
                              'header' if re.match(r'^\d+\.\s+[A-Z][A-Za-z\s]+', chunk_text) else
                              'paragraph')
                start = e.get('start', text.find(chunk_text))
                end = start + len(chunk_text)
                chunks.append((chunk_text, start, end, chunk_type))
        else:
            strategy = "paragraph"

    if strategy == "paragraph" or not chunks:
        raw_chunks = [c.strip() for c in re.split(r'\n{2,}', text) if c.strip()]
        last_end = 0
        for c in raw_chunks:
            start = text.find(c, last_end)
            end = start + len(c)
            chunk_type = ('header' if re.match(r'^\d+\.\s+[A-Z][A-Za-z\s]+', c) else
                          'list_item' if re.match(r'^\d+\.\s|^[\|\*\-]\s', c) else
                          'paragraph')
            chunks.append((c, start, end, chunk_type))
            last_end = end

    # Filter and refine chunks
    final_chunks = []
    for chunk_text, start, end, chunk_type in chunks:
        # Skip very short chunks unless they are list items or headers
        if len(chunk_text.split()) < 5 and chunk_type not in ['list_item', 'header']:
            continue
        # Split large chunks into smaller ones if they exceed max_chunk_size
        if len(chunk_text) > max_chunk_size and chunk_type == 'paragraph':
            sentences = [sent.text.strip() for sent in nlp(chunk_text).sents if sent.text.strip()]
            current_chunk = ""
            for sent in sentences:
                if len(current_chunk) + len(sent) <= max_chunk_size:
                    current_chunk += " " + sent
                else:
                    if current_chunk.strip():
                        final_chunks.append((current_chunk.strip(), start, start + len(current_chunk), 'paragraph'))
                        start += len(current_chunk) + 1
                    current_chunk = sent
            if current_chunk.strip():
                final_chunks.append((current_chunk.strip(), start, start + len(current_chunk), 'paragraph'))
        else:
            final_chunks.append((chunk_text, start, end, chunk_type))

    logging.info(f"Created {len(final_chunks)} chunks: {[f'{t} ({len(c.split())} words)' for c, _, _, t in final_chunks[:5]]}")
    return final_chunks


def extract_components(doc: spacy.tokens.Doc, doc_id: str, lang: str, chunks_with_info: List[tuple[str, int, int, str]]) -> Dict[str, List[Dict[str, Any]]]:
    """Extracts requirements, actors, actions, objects, results, and entities per chunk."""
    components = {
        "requirements": [],
        "actors": [],
        "actions": [],
        "objects": [],
        "results": [],
        "documents": [{"doc_id": doc_id, "name": "Current Document", "type": "doc", "content": doc.text}],
        "entities": []
    }

    requirement_descriptions = set()
    current_section = "unknown"
    req_type = "functional"  # Default requirement type

    for chunk_idx, (chunk_text, start, end, chunk_type) in enumerate(chunks_with_info):
        chunk_id = f"{doc_id}_chunk_{chunk_idx}"
        logging.debug(f"Processing chunk {chunk_id}: type={chunk_type}, text={chunk_text[:100]}...")

        if chunk_type == 'header':
            current_section = chunk_text.strip().lower()
            req_type = ("functional" if any(kw in current_section for kw in ["functional", "feature", "interface", "registration", "investigation", "prosecution", "search", "citizen", "navigation", "configuration"]) else
                        "non-functional")
            logging.debug(f"Detected section: {current_section}, setting req_type to {req_type}")
            continue

        chunk_doc = nlp(chunk_text)
        
        # Handle list items (typically single requirements)
        if chunk_type == 'list_item' or re.match(r'^\d+\.\s|^[\|\*\-]\s', chunk_text):
            req_text = chunk_text.strip()
            if is_requirement_sentence(chunk_doc, lang) or re.match(r'^\d+\.\s|^[\|\*\-]\s', req_text):
                req_id = f"req_{doc_id}_{len(components['requirements'])}"
                req = {
                    "req_id": req_id,
                    "type": req_type,
                    "description": req_text,
                    "chunk_id": chunk_id,
                    "section": current_section
                }
                components["requirements"].append(req)
                requirement_descriptions.add(req_text)
                logging.info(f"Extracted requirement from list_item: {req}")

                # Extract components
                for token in chunk_doc:
                    if token.dep_ == "nsubj" and (token.ent_type_ or token.text.lower() in ["system", "user", "citizen", "police", "admin", "constable"]):
                        actor_id = f"actor_{doc_id}_{len(components['actors'])}"
                        components["actors"].append({"id": actor_id, "name": token.text, "description": f"Role: {token.text}"})
                        req["actor"] = actor_id
                    elif token.pos_ == "VERB" and token.dep_ == "ROOT":
                        action_id = f"action_{doc_id}_{len(components['actions'])}"
                        components["actions"].append({"id": action_id, "name": token.text, "description": f"Action: {token.text}"})
                        req["action"] = action_id
                    elif token.dep_ == "dobj" and token.pos_ in ["NOUN", "PROPN"]:
                        object_id = f"object_{doc_id}_{len(components['objects'])}"
                        components["objects"].append({"id": object_id, "name": token.text, "description": f"Object: {token.text}"})
                        req["object"] = object_id
                    elif token.dep_ == "prep" and token.text.lower() in (["for", "to", "with"] if lang == 'en' else ["для", "к", "с"]):
                        result_id = f"result_{doc_id}_{len(components['results'])}"
                        result_text = ' '.join([t.text for t in token.subtree])
                        components["results"].append({"id": result_id, "description": f"Expected result: {result_text}"})
                        req["result"] = result_id

        # Handle paragraphs (may contain multiple requirements)
        elif chunk_type == 'paragraph':
            for sent in chunk_doc.sents:
                sent_text = sent.text.strip()
                if not sent_text:
                    continue
                sent_doc = nlp(sent_text)
                if is_requirement_sentence(sent_doc, lang) or re.match(r'^\d+\.\s|^[\|\*\-]\s', sent_text):
                    req_id = f"req_{doc_id}_{len(components['requirements'])}"
                    req = {
                        "req_id": req_id,
                        "type": req_type,
                        "description": sent_text,
                        "chunk_id": chunk_id,
                        "section": current_section
                    }
                    components["requirements"].append(req)
                    requirement_descriptions.add(sent_text)
                    logging.info(f"Extracted requirement from paragraph sentence: {req}")

                    # Extract components
                    for token in sent_doc:
                        if token.dep_ == "nsubj" and (token.ent_type_ or token.text.lower() in ["system", "user", "citizen", "police", "admin", "constable"]):
                            actor_id = f"actor_{doc_id}_{len(components['actors'])}"
                            components["actors"].append({"id": actor_id, "name": token.text, "description": f"Role: {token.text}"})
                            req["actor"] = actor_id
                        elif token.pos_ == "VERB" and token.dep_ == "ROOT":
                            action_id = f"action_{doc_id}_{len(components['actions'])}"
                            components["actions"].append({"id": action_id, "name": token.text, "description": f"Action: {token.text}"})
                            req["action"] = action_id
                        elif token.dep_ == "dobj" and token.pos_ in ["NOUN", "PROPN"]:
                            object_id = f"object_{doc_id}_{len(components['objects'])}"
                            components["objects"].append({"id": object_id, "name": token.text, "description": f"Object: {token.text}"})
                            req["object"] = object_id
                        elif token.dep_ == "prep" and token.text.lower() in (["for", "to", "with"] if lang == 'en' else ["для", "к", "с"]):
                            result_id = f"result_{doc_id}_{len(components['results'])}"
                            result_text = ' '.join([t.text for t in token.subtree])
                            components["results"].append({"id": result_id, "description": f"Expected result: {result_text}"})
                            req["result"] = result_id

    # Extract entities using NER from the entire document
    for ent in doc.ents:
        components["entities"].append({
            "entity_id": f"ent_{doc_id}_{len(components['entities'])}",
            "type": ent.label_.lower(),
            "name": ent.text
        })

    # logging.info(f"Extracted {len(components['requirements'])} requirements for doc_id: {doc_id}: {components['requirements']}")
    # logging.info(f"Extracted {len(components['actors'])} actors for doc_id: {doc_id}: {components['actors']}")
    # logging.info(f"Extracted {len(components['actions'])} actions for doc_id: {doc_id}: {components['actions']}")
    # logging.info(f"Extracted {len(components['objects'])} objects for doc_id: {doc_id}: {components['objects']}")
    # logging.info(f"Extracted {len(components['results'])} results for doc_id: {doc_id}: {components['results']}")
    # logging.info(f"Extracted {len(components['entities'])} entities for doc_id: {doc_id}: {components['entities']}")

    return components


async def build_rag_graph_from_text(doc_id: str, filename: str, text: str, db: KuzuDBClient = None):
    logging.info(f"Starting RAG graph build for doc_id: {doc_id}")
    try:
        lang = detect(text)
        logging.info(f"Detected language: {lang}")
    except LangDetectException:
        lang = "en"
        logging.warning("Language detection failed, defaulting to English")

    global nlp_ru, nlp_en, nlp
    nlp = nlp_en if lang == "en" else nlp_ru
    if not nlp:
        logging.error(f"No SpaCy model loaded for language: {lang}")
        raise ValueError(f"No SpaCy model for {lang}")

    text = re.sub(r'\n+', '\n', text.strip())
    lines = [line.strip() + '.' if line.strip() and not line.strip().endswith('.') else line.strip() for line in text.split('\n')]
    text = ' '.join(lines)

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

        chunks_with_info = chunk_text(text)
        text_chunks = [chunk for chunk, _, _, _ in chunks_with_info]
        embeddings = embedding_pipeline.encode(text_chunks, batch_size=32)

        doc = nlp(text)
        components = extract_components(doc, doc_id, lang=lang, chunks_with_info=chunks_with_info)

        conn.execute(f"""
            MERGE (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
            ON CREATE SET d.filename = $filename, d.processed_at = $processed_at, d.status = $status, d.created_at = $created_at, d.updated_at = $updated_at
            ON MATCH SET d.filename = $filename, d.processed_at = $processed_at, d.status = $status, d.updated_at = $updated_at
        """, {
            "doc_id": doc_id, "filename": filename, "processed_at": now,
            "status": "processing", "created_at": now, "updated_at": now
        })

        for i, (chunks, start, end, chunk_type) in enumerate(chunks_with_info):
            chunk_id = f"{doc_id}_chunk_{i}"
            conn.execute(f"""
                CREATE (c:{CHUNK_TABLE} {{chunk_id: $chunk_id, doc_id: $doc_id, text: $text, embedding: $embedding}})
            """, {
                "chunk_id": chunk_id, "doc_id": doc_id, "text": chunks, "embedding": embeddings[i].tolist()
            })
            conn.execute(f"""
                MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}}),
                      (c:{CHUNK_TABLE} {{chunk_id: $chunk_id}})
                CREATE (d)-[:{CONTAINS_RELATIONSHIP}]->(c)
            """, {"doc_id": doc_id, "chunk_id": chunk_id})

        for actor in components["actors"]:
            conn.execute(f"CREATE (a:{ACTOR_TABLE} {{id: $id, name: $name, description: $description}})", actor)
        for action in components["actions"]:
            conn.execute(f"CREATE (a:{ACTION_TABLE} {{id: $id, name: $name, description: $description}})", action)
        for obj in components["objects"]:
            conn.execute(f"CREATE (o:{OBJECT_TABLE} {{id: $id, name: $name, description: $description}})", obj)
        for result in components["results"]:
            conn.execute(f"CREATE (r:{RESULT_TABLE} {{id: $id, description: $description}})", result)
        for ent in components["entities"]:
            conn.execute(f"""
                CREATE (e:{ENTITY_TABLE} {{entity_id: $entity_id, type: $type, name: $name}})
            """, {
                "entity_id": ent["entity_id"], "type": ent["type"], "name": ent["name"]
            })

        for req in components["requirements"]:
            conn.execute(f"""
                CREATE (r:{REQUIREMENT_TABLE} {{req_id: $req_id, type: $type, description: $description, created_at: $created_at}})
            """, {
                "req_id": req["req_id"], "type": req["type"], "description": req["description"], "created_at": now
            })
            if "actor" in req:
                conn.execute(f"""
                    MATCH (r:{REQUIREMENT_TABLE} {{req_id: $req_id}}),
                          (a:{ACTOR_TABLE} {{id: $actor_id}})
                    CREATE (r)-[:{PERFORMS_RELATIONSHIP}]->(a)
                """, {"req_id": req["req_id"], "actor_id": req["actor"]})
            if "action" in req:
                conn.execute(f"""
                    MATCH (r:{REQUIREMENT_TABLE} {{req_id: $req_id}}),
                          (a:{ACTION_TABLE} {{id: $action_id}})
                    CREATE (r)-[:{COMMITS_RELATIONSHIP}]->(a)
                """, {"req_id": req["req_id"], "action_id": req["action"]})
            if "object" in req:
                conn.execute(f"""
                    MATCH (r:{REQUIREMENT_TABLE} {{req_id: $req_id}}),
                          (o:{OBJECT_TABLE} {{id: $object_id}})
                    CREATE (r)-[:{ON_WHAT_PERFORMED_RELATIONSHIP}]->(o)
                """, {"req_id": req["req_id"], "object_id": req["object"]})
            if "result" in req:
                conn.execute(f"""
                    MATCH (r:{REQUIREMENT_TABLE} {{req_id: $req_id}}),
                          (res:{RESULT_TABLE} {{id: $result_id}})
                    CREATE (r)-[:{EXPECTS_RELATIONSHIP}]->(res)
                """, {"req_id": req["req_id"], "result_id": req["result"]})
            if "chunk_id" in req:
                conn.execute(f"""
                    MATCH (r:{REQUIREMENT_TABLE} {{req_id: $req_id}}),
                          (c:{CHUNK_TABLE} {{chunk_id: $chunk_id}})
                    CREATE (r)-[:{DESCRIBED_BY_RELATIONSHIP}]->(c)
                """, {"req_id": req["req_id"], "chunk_id": req["chunk_id"]})
            conn.execute(f"""
                MATCH (r:{REQUIREMENT_TABLE} {{req_id: $req_id}}),
                      (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
                CREATE (r)-[:{REFERENCES_RELATIONSHIP}]->(d)
            """, {"req_id": req["req_id"], "doc_id": doc_id})

        conn.execute(f"""
            MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
            SET d.status = 'indexed', d.updated_at = $updated_at
        """, {"doc_id": doc_id, "updated_at": now})

        logging.info(f"Built RAG graph with {len(components['requirements'])} requirements for doc_id: {doc_id}")
    except Exception as e:
        logging.error(f"Error building RAG graph: {e}", exc_info=True)
        if db is not None:
            now = datetime.now().isoformat()
            db.execute(f"""
                MATCH (d:{DOCUMENT_TABLE} {{doc_id: $doc_id}})
                SET d.status = 'error', d.updated_at = $updated_at, d.error = $error_msg
            """, {"doc_id": doc_id, "updated_at": now, "error_msg": str(e)})
        raise
    finally:
        if 'close_db' in locals() and close_db:
            db.close()

async def fetch_requirements(doc_id: str | None = None, req_type: str | None = None, db: KuzuDBClient = Depends(get_db)) -> List[Dict[str, Any]]:
    conn = db
    query = f"""
        MATCH (r:{REQUIREMENT_TABLE})
        OPTIONAL MATCH (r)-[:{REFERENCES_RELATIONSHIP}]->(d:{DOCUMENT_TABLE})
        OPTIONAL MATCH (r)-[:{DESCRIBED_BY_RELATIONSHIP}]->(c:{CHUNK_TABLE})
        OPTIONAL MATCH (r)-[:{IMPLEMENTS_RELATIONSHIP}]->(e:{ENTITY_TABLE})
    """
    conditions = []
    params = {}
    if doc_id:
        conditions.append("d.doc_id = $doc_id")
        params["doc_id"] = doc_id
    if req_type:
        conditions.append("r.type = $req_type")
        params["req_type"] = req_type
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
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
            "chunks": row[4] if row[4] else [],
            "entities": row[5] if row[5] else [],
            "document_id": row[6]
        })
    return requirements

async def reindex_document(doc_id: str, db: KuzuDBClient = Depends(get_db)):
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
            if file_path.endswith('.pdf'):
                doc = nlp(file_path)
                text = doc.text
                if not text or text.isspace():
                    raise ValueError("No text extracted from PDF")
            else:
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
        raise HTTPException(status_code=500, detail=str(e))