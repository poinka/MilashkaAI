from typing import List, Dict, Any
import numpy as np
import logging
from langdetect import detect
from app.db.kuzudb_client import get_db, KuzuDBClient
from app.core.models import get_embedding_pipeline
from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('/app/requirements.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

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

def format_context(context: Dict, lang: str = "ru") -> str:
    """Format context in the specified language."""
    if lang == "en":
        header = "Context for autocompletion of functional requirement text:\n\n"
        req_label = "Requirement"
        desc_label = "Description"
        actor_label = "Actor"
        action_label = "Action"
        object_label = "Object"
        result_label = "Result"
        doc_label = "Related document"
        doc_name_label = "Name"
        doc_content_label = "Content"
        ui_label = "Previous user interaction"
        ui_suggestion_label = "System suggestion"
        ui_reaction_label = "User reaction"
        rel_req_label = "Related requirement"
    else:  # Russian
        header = "Контекст для автодополнения текста функционального требования:\n\n"
        req_label = "Требование"
        desc_label = "Описание"
        actor_label = "Актор"
        action_label = "Действие"
        object_label = "Объект"
        result_label = "Результат"
        doc_label = "Связанный документ"
        doc_name_label = "Название"
        doc_content_label = "Содержание"
        ui_label = "Предыдущее взаимодействие с пользователем"
        ui_suggestion_label = "Предложение системы"
        ui_reaction_label = "Реакция пользователя"
        rel_req_label = "Связанное требование"

    context_text = header
    for i, req in enumerate(context["requirements"], 1):
        context_text += f"{i}. {req_label} {req['req_id']} ({req['type']}):\n"
        context_text += f"   - {desc_label}: {req['description']}\n"
        if req["actor"]:
            context_text += f"   - {actor_label}: {req['actor']}\n"
        if req["action"]:
            context_text += f"   - {action_label}: {req['action']}\n"
        if req["object"]:
            context_text += f"   - {object_label}: {req['object']}\n"
        if req["result"]:
            context_text += f"   - {result_label}: {req['result']}\n"
    for i, doc in enumerate(context["documents"], 1):
        context_text += f"\n{i}. {doc_label}:\n"
        context_text += f"   - {doc_name_label}: {doc['name']}\n"
        context_text += f"   - {doc_content_label}: {doc['content'][:200]}...\n"
    for i, ui in enumerate(context["user_interactions"], 1):
        context_text += f"\n{i}. {ui_label}:\n"
        context_text += f"   - {ui_suggestion_label}: {ui['suggestion_text']}\n"
        context_text += f"   - {ui_reaction_label}: {ui['user_reaction']}\n"
    for i, r2 in enumerate(context["related_requirements"], 1):
        context_text += f"\n{i}. {rel_req_label}:\n"
        context_text += f"   - {desc_label}: {r2['description']}\n"

    return context_text

async def retrieve_relevant_chunks(
    query_text: str,
    embedding_pipeline=None,
    db: KuzuDBClient = None,
    filter_doc_id: str = None,
    top_k: int = 3,
    preferred_language: str = None
) -> List[Dict]:
    """Retrieve relevant chunks and related graph data for a query."""
    close_db = False
    if db is None:
        db = KuzuDBClient(settings.KUZUDB_PATH)
        db.connect()
        close_db = True

    try:
        if embedding_pipeline is None:
            embedding_pipeline = get_embedding_pipeline()

        # Detect query language
        try:
            query_lang = detect(query_text)
            logger.info(f"Detected query language: {query_lang}")
        except:
            query_lang = "ru"
            logger.warning("Language detection failed, defaulting to Russian")

        # Use preferred language if provided, else fall back to query language
        context_lang = preferred_language if preferred_language in ["ru", "en"] else query_lang

        # Generate query embedding
        query_vector = embedding_pipeline.encode([query_text])[0]
        query_vector_list = [float(x) for x in query_vector.tolist()]
        max_abs = max(map(abs, query_vector_list), default=1)
        if max_abs > 1e6:
            query_vector_list = [x/max_abs for x in query_vector_list]

        # Step 1: Find top-k chunks using vector similarity (cosine similarity)
        chunk_query = f"""
            MATCH (c:{CHUNK_TABLE})
            WHERE c.embedding IS NOT NULL
        """
        if filter_doc_id:
            chunk_query += f" AND c.doc_id = $doc_id"
        chunk_query += f"""
            RETURN c.chunk_id, c.text, c.doc_id, c.embedding
            ORDER BY 1.0 - (
                reduce(sum = 0.0, x IN range(0, size(c.embedding)-1) | sum + c.embedding[x] * $query_vector[x]) /
                (sqrt(reduce(sum = 0.0, x IN c.embedding | sum + x*x)) *
                 sqrt(reduce(sum = 0.0, x IN $query_vector | sum + x*x)))
            )
            LIMIT $top_k
        """
        params = {"query_vector": query_vector_list, "top_k": top_k}
        if filter_doc_id:
            params["doc_id"] = filter_doc_id
        results = db.execute(chunk_query, params)

        chunks = []
        chunk_ids = []
        while results.has_next():
            row = results.get_next()
            chunk_ids.append(row[0])
            chunks.append({
                "text": row[1],
                "score": 1.0,  # Simplified, as KuzuDB computes similarity
                "metadata": {"doc_id": row[2], "chunk_id": row[0]}
            })

        if not chunks:
            logger.warning("No chunks found for query")
            return []

        # Step 2: Enrich chunks with graph data
        enriched_results = []
        for chunk in chunks:
            chunk_id = chunk["metadata"]["chunk_id"]
            doc_id = chunk["metadata"]["doc_id"]

            # Fetch related requirements and their connections
            graph_query = f"""
                MATCH (c:{CHUNK_TABLE} {{chunk_id: $chunk_id}})
                OPTIONAL MATCH (r:{REQUIREMENT_TABLE})-[:{DESCRIBED_BY_RELATIONSHIP}]->(c)
                OPTIONAL MATCH (r)-[:{PERFORMS_RELATIONSHIP}]->(a:{ACTOR_TABLE})
                OPTIONAL MATCH (r)-[:{COMMITS_RELATIONSHIP}]->(act:{ACTION_TABLE})
                OPTIONAL MATCH (r)-[:{ON_WHAT_PERFORMED_RELATIONSHIP}]->(o:{OBJECT_TABLE})
                OPTIONAL MATCH (r)-[:{EXPECTS_RELATIONSHIP}]->(res:{RESULT_TABLE})
                OPTIONAL MATCH (r)-[:{DESCRIBED_IN_RELATIONSHIP}]->(d:{DOCUMENT_TABLE})
                OPTIONAL MATCH (r)-[:{LINKED_TO_FEEDBACK_RELATIONSHIP}]->(ui:{USER_INTERACTION_TABLE})
                OPTIONAL MATCH (r)-[:{DEPENDS_ON_RELATIONSHIP}]->(r2:{REQUIREMENT_TABLE})
                RETURN r, a, act, o, res, d, ui, r2
            """
            graph_results = db.execute(graph_query, {"chunk_id": chunk_id})

            context = {
                "requirements": [],
                "documents": [],
                "user_interactions": [],
                "related_requirements": []
            }
            while graph_results.has_next():
                row = graph_results.get_next()
                req = row[0]
                if req:
                    req_data = {
                        "req_id": req["req_id"],
                        "type": req["type"],
                        "description": req["description"],
                        "actor": row[1]["name"] if row[1] else None,
                        "action": row[2]["name"] if row[2] else None,
                        "object": row[3]["name"] if row[3] else None,
                        "result": row[4]["description"] if row[4] else None
                    }
                    context["requirements"].append(req_data)
                if row[5]:
                    context["documents"].append({
                        "id": row[5]["id"],
                        "name": row[5]["name"],
                        "content": row[5]["content"]
                    })
                if row[6]:
                    context["user_interactions"].append({
                        "id": row[6]["id"],
                        "suggestion_text": row[6]["suggestion_text"],
                        "user_reaction": row[6]["user_reaction"],
                        "date": row[6]["date"]
                    })
                if row[7]:
                    context["related_requirements"].append({
                        "req_id": row[7]["req_id"],
                        "description": row[7]["description"]
                    })

            # Format context in the appropriate language
            context_text = format_context(context, lang=context_lang)

            enriched_results.append({
                "chunk": chunk["text"],
                "score": chunk["score"],
                "metadata": chunk["metadata"],
                "context": context_text,
                "language": context_lang
            })

        return enriched_results
    except Exception as e:
        logger.error(f"Error in retrieve_relevant_chunks: {e}", exc_info=True)
        return []
    finally:
        if close_db:
            db.close()