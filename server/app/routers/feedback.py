from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging
from datetime import datetime

from app.db.kuzudb_client import get_db_connection

router = APIRouter()

class SuggestionFeedback(BaseModel):
    suggestion_text: str
    document_context: Optional[str] = None
    was_accepted: bool
    source: str = "completion" # Can be 'completion', 'edit', or 'voice'
    language: str = "ru"
    user_id: Optional[str] = None
    metadata: Optional[dict] = None

@router.post("/track-suggestion",
    summary="Track accepted/rejected suggestions to improve model")
async def track_suggestion_feedback(feedback: SuggestionFeedback):
    """
    Record user feedback on suggestions to improve future recommendations.
    Tracks whether suggestions were accepted or rejected.
    """
    db = get_db_connection()
    
    try:
        # Use a dedicated graph for feedback tracking
        graph_name = "suggestion_feedback"
        graph = db.select_graph(graph_name)
        
        # Generate a unique ID for this feedback instance
        feedback_id = f"feedback_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
        
        # Create a feedback node with all relevant properties
        result = graph.query("""
            CREATE (f:Feedback {
                feedback_id: $feedback_id,
                suggestion_text: $suggestion_text,
                document_context: $document_context,
                was_accepted: $was_accepted,
                source: $source,
                language: $language,
                user_id: $user_id,
                timestamp: $timestamp
            })
            RETURN f.feedback_id
        """, params={
            "feedback_id": feedback_id,
            "suggestion_text": feedback.suggestion_text,
            "document_context": feedback.document_context or "",
            "was_accepted": feedback.was_accepted,
            "source": feedback.source,
            "language": feedback.language,
            "user_id": feedback.user_id or "anonymous",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Add metadata properties if provided
        if feedback.metadata:
            property_updates = []
            for key, value in feedback.metadata.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    property_updates.append(f"f.{key} = ${key}")
            
            if property_updates:
                set_clause = ", ".join(property_updates)
                graph.query(f"""
                    MATCH (f:Feedback {{feedback_id: $feedback_id}})
                    SET {set_clause}
                """, params={"feedback_id": feedback_id, **feedback.metadata})
        
        # Track entity relationships if document context is provided
        if feedback.document_context:
            try:
                # Find entities mentioned in the suggestion
                # This helps build connection between suggestion feedback and content
                doc = get_nlp()(feedback.suggestion_text)
                for ent in doc.ents:
                    entity_name = ent.text
                    entity_type = ent.label_
                    
                    # Create entity and relationship
                    graph.query("""
                        MATCH (f:Feedback {feedback_id: $feedback_id})
                        MERGE (e:FeedbackEntity {name: $name, type: $type})
                        MERGE (f)-[r:MENTIONS_ENTITY]->(e)
                        SET r.count = COALESCE(r.count, 0) + 1
                    """, params={
                        "feedback_id": feedback_id,
                        "name": entity_name,
                        "type": entity_type
                    })
            except Exception as e:
                logging.warning(f"Error extracting entities from suggestion: {e}")
        
        # Calculate and update acceptance statistics for similar suggestions
        try:
            # Find similar suggestions by exact text match
            similar_results = graph.query("""
                MATCH (f:Feedback)
                WHERE f.suggestion_text = $text AND f.feedback_id <> $feedback_id
                RETURN COUNT(f) as total,
                       SUM(CASE WHEN f.was_accepted THEN 1 ELSE 0 END) as accepted
            """, params={
                "text": feedback.suggestion_text,
                "feedback_id": feedback_id
            })
            
            if similar_results.result_set and len(similar_results.result_set) > 0:
                total = similar_results.result_set[0][0] or 0
                accepted = similar_results.result_set[0][1] or 0
                
                if total > 0:
                    acceptance_rate = accepted / total
                    # Update statistics on the current feedback
                    graph.query("""
                        MATCH (f:Feedback {feedback_id: $feedback_id})
                        SET f.similar_suggestions = $total,
                            f.similar_accepted = $accepted,
                            f.acceptance_rate = $rate
                    """, params={
                        "feedback_id": feedback_id,
                        "total": total + 1,  # Include current feedback
                        "accepted": accepted + (1 if feedback.was_accepted else 0),
                        "rate": acceptance_rate
                    })
        except Exception as e:
            logging.warning(f"Error calculating acceptance statistics: {e}")
        
        return {
            "status": "success",
            "feedback_id": feedback_id,
            "message": "Suggestion feedback recorded successfully"
        }
        
    except Exception as e:
        logging.error(f"Error tracking suggestion feedback: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to track suggestion feedback: {str(e)}"
        )

@router.get("/suggestion-stats",
    summary="Get statistics about suggestion acceptance rates")
async def get_suggestion_statistics(
    source: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 100
):
    """
    Get statistics about suggestion acceptance rates to help improve the model.
    """
    db = get_db_connection()
    
    try:
        graph_name = "suggestion_feedback"
        graph = db.select_graph(graph_name)
        
        # Build query based on filters
        match_clause = "MATCH (f:Feedback)"
        where_conditions = []
        params = {"limit": limit}
        
        if source:
            where_conditions.append("f.source = $source")
            params["source"] = source
            
        if language:
            where_conditions.append("f.language = $language")
            params["language"] = language
            
        where_clause = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        
        # Get overall stats
        overall_result = graph.query(f"""
            {match_clause}
            {where_clause}
            WITH COUNT(f) AS total, 
                 SUM(CASE WHEN f.was_accepted THEN 1 ELSE 0 END) AS accepted
            RETURN total, accepted, CASE WHEN total > 0 THEN toFloat(accepted)/total ELSE 0 END AS acceptance_rate
        """, params=params)
        
        # Get top accepted suggestions
        top_accepted = graph.query(f"""
            {match_clause}
            {where_clause} AND f.was_accepted = true
            WITH f.suggestion_text AS suggestion, COUNT(*) AS count
            ORDER BY count DESC
            LIMIT $limit
            RETURN suggestion, count
        """, params=params)
        
        # Get top rejected suggestions
        top_rejected = graph.query(f"""
            {match_clause}
            {where_clause} AND f.was_accepted = false
            WITH f.suggestion_text AS suggestion, COUNT(*) AS count
            ORDER BY count DESC
            LIMIT $limit
            RETURN suggestion, count
        """, params=params)
        
        # Format results
        overall = {
            "total_suggestions": 0,
            "accepted_count": 0,
            "acceptance_rate": 0
        }
        
        if overall_result.result_set and len(overall_result.result_set) > 0:
            overall["total_suggestions"] = overall_result.result_set[0][0] or 0
            overall["accepted_count"] = overall_result.result_set[0][1] or 0
            overall["acceptance_rate"] = overall_result.result_set[0][2] or 0
        
        accepted_suggestions = []
        for row in top_accepted.result_set:
            if row[0]:  # Skip null values
                accepted_suggestions.append({
                    "text": row[0],
                    "count": row[1] or 0
                })
        
        rejected_suggestions = []
        for row in top_rejected.result_set:
            if row[0]:  # Skip null values
                rejected_suggestions.append({
                    "text": row[0],
                    "count": row[1] or 0
                })
        
        return {
            "overall_statistics": overall,
            "top_accepted": accepted_suggestions,
            "top_rejected": rejected_suggestions
        }
        
    except Exception as e:
        logging.error(f"Error getting suggestion statistics: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get suggestion statistics: {str(e)}"
        )

def get_nlp():
    """Helper function to access SpaCy NLP model"""
    from app.core.rag_builder import nlp
    return nlp
