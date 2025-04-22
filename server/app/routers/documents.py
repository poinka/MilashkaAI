import logging
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import List
import aiofiles
import os
import uuid
from datetime import datetime

from app.core.config import settings
from app.schemas.models import DocumentMetadata
from app.schemas.errors import ErrorResponse
from app.core.rag_builder import build_rag_graph_from_text 
from app.db.kuzudb_client import get_db_connection

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

router = APIRouter(
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse}
    }
)

async def save_upload_file(file: UploadFile, id: str) -> str:
    # Use the consistent path from settings
    uploads_path = settings.UPLOADS_PATH
    os.makedirs(uploads_path, exist_ok=True)
    
    ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{id}{ext}"
    file_path = os.path.join(uploads_path, unique_filename)
    
    async with aiofiles.open(file_path, 'wb') as out_file:
        content = await file.read()
        await out_file.write(content)
    
    return file_path

@router.post("/upload", 
    response_model=DocumentMetadata,
    summary="Upload a document for processing")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    if file.size and file.size > settings.MAX_DOCUMENT_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds maximum limit of {settings.MAX_DOCUMENT_SIZE / 1024 / 1024}MB"
        )
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in settings.SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Supported formats: {', '.join(settings.SUPPORTED_FORMATS)}"
        )

    try:
        doc_id = str(uuid.uuid4())
        file_path = await save_upload_file(file, doc_id)
        now = datetime.utcnow()
        metadata = DocumentMetadata(
            doc_id=doc_id,
            filename=file.filename,
            processed_at=now,
            status="processing",
            created_at=now,
            updated_at=now,
            error=None
        )

        background_tasks.add_task(
            build_rag_graph_from_text, 
            doc_id=doc_id, 
            filename=file.filename, 
            text="Текст извлеченный из файла..." 
        )

        return metadata

    except Exception as e:
        if 'file_path' in locals():
            try:
                os.remove(file_path)
            except:
                pass
        
        raise HTTPException(
            status_code=500,
            detail=f"Error processing upload: {str(e)}"
        )

@router.get("/",
    response_model=List[DocumentMetadata], # Correct response model
    summary="List all uploaded documents")
def list_documents():
    """Retrieves metadata for all processed documents."""
    try:
        db = get_db_connection()
        # Query KùzuDB for Document nodes, including processed_at
        query = """ 
            MATCH (d:Document) 
            RETURN d.doc_id, d.filename, d.status, d.created_at, d.updated_at, d.processed_at
        """
        results = db.execute(query)
        
        documents = []
        while results.has_next():
            row = results.get_next()
            # Ensure timestamps are parsed correctly if stored as strings
            created_at = row[3]
            updated_at = row[4]
            processed_at = row[5] # Get processed_at from query result

            # --- Timestamp Parsing Logic --- 
            if isinstance(created_at, str):
                try:
                    # Attempt parsing common ISO formats, handling potential 'Z' for UTC
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                except ValueError:
                    logger.warning(f"Could not parse created_at timestamp: {row[3]}. Using current time as fallback.")
                    created_at = datetime.utcnow() # Fallback
            elif not isinstance(created_at, datetime):
                 logger.warning(f"created_at is not a string or datetime: {type(created_at)}. Using current time as fallback.")
                 created_at = datetime.utcnow()
                 
            if isinstance(updated_at, str):
                try:
                    updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                except ValueError:
                    logger.warning(f"Could not parse updated_at timestamp: {row[4]}. Using current time as fallback.")
                    updated_at = datetime.utcnow() # Fallback
            elif not isinstance(updated_at, datetime):
                 logger.warning(f"updated_at is not a string or datetime: {type(updated_at)}. Using current time as fallback.")
                 updated_at = datetime.utcnow()

            # Parse processed_at
            if isinstance(processed_at, str):
                try:
                    processed_at = datetime.fromisoformat(processed_at.replace('Z', '+00:00'))
                except ValueError:
                    logger.warning(f"Could not parse processed_at timestamp: {row[5]}. Using current time as fallback.")
                    processed_at = datetime.utcnow() # Fallback
            elif not isinstance(processed_at, datetime):
                 logger.warning(f"processed_at is not a string or datetime: {type(processed_at)}. Using current time as fallback.")
                 processed_at = datetime.utcnow()
            # --- End Timestamp Parsing --- 

            documents.append(DocumentMetadata(
                doc_id=row[0],
                filename=row[1],
                status=row[2] if row[2] else "unknown",
                created_at=created_at,
                updated_at=updated_at,
                error=None, 
                processed_at=processed_at # Use the parsed processed_at value
            ))
            
        logger.info(f"Retrieved {len(documents)} documents from database.")
        return documents

    except Exception as e:
        logger.error(f"Error listing documents: {str(e)}", exc_info=True)
        # Raise HTTPException for explicit error handling on the client side
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve documents: {str(e)}"
        )

@router.get("/{doc_id}", 
    response_model=DocumentMetadata,
    summary="Get document status")
async def get_document_status(doc_id: str):
    try:
        conn = get_db_connection()
        
        result = conn.execute("""
            MATCH (d:Document {doc_id: $doc_id})
            RETURN d.doc_id, d.filename, d.updated_at, d.status, d.created_at, d.updated_at
        """, {"doc_id": doc_id})
        
        if not result.has_next():
            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )

        record = result.get_next()
        
        # Parse timestamps, using updated_at for processed_at
        processed_at = record[2] # This is updated_at from the query
        created_at = record[4]
        updated_at = record[5]

        if isinstance(processed_at, str):
            try:
                processed_at = datetime.fromisoformat(processed_at.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"Could not parse processed_at/updated_at timestamp: {record[2]}. Using current time.")
                processed_at = datetime.utcnow()
        elif not isinstance(processed_at, datetime):
            logger.warning(f"processed_at/updated_at is not string or datetime: {type(processed_at)}. Using current time.")
            processed_at = datetime.utcnow()

        # Reuse parsing logic for created_at and updated_at if needed, similar to list_documents
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"Could not parse created_at timestamp: {record[4]}. Using current time.")
                created_at = datetime.utcnow()
        elif not isinstance(created_at, datetime):
            logger.warning(f"created_at is not string or datetime: {type(created_at)}. Using current time.")
            created_at = datetime.utcnow()

        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"Could not parse updated_at timestamp: {record[5]}. Using current time.")
                updated_at = datetime.utcnow()
        elif not isinstance(updated_at, datetime):
            logger.warning(f"updated_at is not string or datetime: {type(updated_at)}. Using current time.")
            updated_at = datetime.utcnow()
            
        document = DocumentMetadata(
            doc_id=record[0],
            filename=record[1],
            processed_at=processed_at, # Use the parsed updated_at value
            status=record[3] if record[3] is not None else "indexed",
            created_at=created_at,
            updated_at=updated_at,
            error=None
        )
        
        return document
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving document {doc_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving document: {str(e)}"
        )

@router.delete("/{doc_id}",
    # Return a simple success message or status code instead of full metadata
    status_code=204, # No Content is typical for successful DELETE
    summary="Delete a document and its associated data")
async def delete_document(doc_id: str):
    """Deletes a document node, its chunks, and the original file."""
    try:
        conn = get_db_connection()
        
        # 1. Get the filename *before* deleting the node
        filename_result = conn.execute(
            "MATCH (d:Document {doc_id: $doc_id}) RETURN d.filename",
            {"doc_id": doc_id}
        )
        
        original_filename = None
        if filename_result.has_next():
            original_filename = filename_result.get_next()[0]
        else:
            # Document not found in DB, maybe already deleted?
            logger.warning(f"Document node {doc_id} not found in DB for deletion.")

        # 2. Delete the document and associated chunks from the database
        conn.execute("""
            MATCH (d:Document {doc_id: $doc_id})
            OPTIONAL MATCH (d)-[:Contains]->(c:Chunk)
            DETACH DELETE d, c
        """, {"doc_id": doc_id})
        logger.info(f"Deleted document node {doc_id} and associated chunks from KuzuDB.")

        # 3. Delete the original file from the uploads directory
        if original_filename:
            # Reconstruct the unique filename used during upload
            ext = os.path.splitext(original_filename)[1]
            unique_filename = f"{doc_id}{ext}"
            file_path = os.path.join(settings.UPLOADS_PATH, unique_filename)
            
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted file from disk: {file_path}")
                except OSError as e:
                    logger.error(f"Error deleting file {file_path}: {e}", exc_info=True)
                    # Log the error, the main goal (DB removal) is done.
            else:
                logger.warning(f"File not found on disk for deletion: {file_path}")
        else:
             logger.warning(f"Could not determine filename for doc_id {doc_id} to delete from disk.")

        # Return No Content on success
        return None 

    except Exception as e:
        logger.error(f"Error deleting document {doc_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting document: {str(e)}"
        )