from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging
from datetime import datetime

from app.db.kuzudb_client import get_db, KuzuDBClient

router = APIRouter()
logger = logging.getLogger(__name__)

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
async def track_suggestion_feedback(feedback: SuggestionFeedback, db: KuzuDBClient = Depends(get_db)):
    """
    Record user feedback on suggestions to improve future recommendations.
    Tracks whether suggestions were accepted or rejected.
    """
    
    try:
        # First, ensure Feedback table exists
        try:
            db.execute("""
                CREATE NODE TABLE IF NOT EXISTS Feedback (
                    feedback_id STRING,
                    suggestion_text STRING,
                    document_context STRING,
                    was_accepted BOOL,
                    source STRING,
                    language STRING,
                    user_id STRING,
                    timestamp STRING,
                    PRIMARY KEY (feedback_id)
                )
            """)
        except Exception as schema_err:
            logger.warning(f"Could not ensure Feedback schema: {schema_err}")

        # Generate a unique ID for this feedback instance
        feedback_id = f"feedback_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
        
        # Create a feedback node with all relevant properties
        db.execute("""
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
        """, {
            "feedback_id": feedback_id,
            "suggestion_text": feedback.suggestion_text,
            "document_context": feedback.document_context or "",
            "was_accepted": feedback.was_accepted,
            "source": feedback.source,
            "language": feedback.language,
            "user_id": feedback.user_id or "anonymous",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Add metadata properties if provided (simplified)
        if feedback.metadata:
            for key, value in feedback.metadata.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    try:
                        db.execute(f"""
                            MATCH (f:Feedback {{feedback_id: $feedback_id}})
                            SET f.{key} = $value
                        """, {"feedback_id": feedback_id, "value": value})
                    except Exception as meta_err:
                        logger.warning(f"Failed to set metadata property {key}: {meta_err}")

        return {
            "status": "success",
            "feedback_id": feedback_id,
            "message": "Suggestion feedback recorded successfully"
        }
        
    except Exception as e:
        logger.error(f"Error tracking suggestion feedback: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to track suggestion feedback: {str(e)}"
        )

@router.get("/suggestion-stats",
    summary="Get statistics about suggestion acceptance rates")
async def get_suggestion_statistics(
    source: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 100,
    db: KuzuDBClient = Depends(get_db)
):
    """
    Get statistics about suggestion acceptance rates to help improve the model.
    """
    
    try:
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
        overall_result = db.execute(f"""
            {match_clause}
            {where_clause}
            RETURN COUNT(f) AS total, 
                   COUNT(CASE WHEN f.was_accepted = true THEN 1 END) AS accepted
        """, params)

        # Format results
        total = 0
        accepted = 0
        if overall_result:
            row = overall_result.fetchone()
            if row:
                total = row[0] if row[0] is not None else 0
                accepted = row[1] if row[1] is not None else 0
        
        return {
            "overall_statistics": {
                "total_suggestions": total,
                "accepted_count": accepted,
                "acceptance_rate": accepted / total if total > 0 else 0
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting suggestion statistics: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get suggestion statistics: {str(e)}"
        )
