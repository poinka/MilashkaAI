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
    response_model=dict,
    summary="List all uploaded documents")
def list_documents():
    logger.info("Handling GET /api/v1/documents/ request")
    try:
        logger.debug("Attempting to get database connection")
        conn = get_db_connection()
        logger.debug("Database connection established successfully")
        
        logger.debug("Ensuring Document table exists")
        conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Document (
                doc_id STRING,
                filename STRING,
                processed_at STRING,
                status STRING,
                created_at STRING,
                updated_at STRING,
                PRIMARY KEY (doc_id)
            )
        """)
        logger.debug("Document table ensured")
        
        logger.debug("Executing query to fetch documents")
        result = conn.execute("""
            MATCH (d:Document)
            RETURN d.doc_id, d.filename, d.processed_at, d.status, d.created_at, d.updated_at
        """)
        documents = []
        while result.has_next():
            row = result.get_next()
            logger.debug(f"Fetched document row: {row}")
            documents.append({
                "doc_id": row[0],
                "filename": row[1],
                "processed_at": row[2],
                "status": row[3] if row[3] is not None else "indexed",
                "created_at": row[4] if row[4] is not None else datetime.now().isoformat(),
                "updated_at": row[5] if row[5] is not None else datetime.now().isoformat(),
                "error": None
            })
        logger.info(f"Successfully fetched {len(documents)} documents")
        return {"documents": documents}
    except Exception as e:
        logger.error(f"Error listing documents: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list documents: {str(e)}"
        )

@router.get("/{doc_id}", 
    response_model=DocumentMetadata,
    summary="Get document status")
async def get_document_status(doc_id: str):
    try:
        conn = get_db_connection()
        
        result = conn.execute("""
            MATCH (d:Document {doc_id: $doc_id})
            RETURN d.doc_id, d.filename, d.processed_at, d.status, d.created_at, d.updated_at
        """, {"doc_id": doc_id})
        
        if not result.has_next():
            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )
            
        record = result.get_next()
        document = DocumentMetadata(
            doc_id=record[0],
            filename=record[1],
            processed_at=datetime.fromisoformat(record[2]) if record[2] else datetime.utcnow(),
            status=record[3] if record[3] is not None else "indexed",
            created_at=datetime.fromisoformat(record[4]) if record[4] else datetime.utcnow(),
            updated_at=datetime.fromisoformat(record[5]) if record[5] is not None else datetime.utcnow(),
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
    response_model=DocumentMetadata,
    summary="Delete a document")
async def delete_document(doc_id: str):
    try:
        conn = get_db_connection()
        
        document = await get_document_status(doc_id)

        # Delete the document and associated chunks from the database
        conn.execute("""
            MATCH (d:Document {doc_id: $doc_id})
            OPTIONAL MATCH (d)-[:Contains]->(c:Chunk)
            DETACH DELETE d, c
        """, {"doc_id": doc_id})
        
        # Attempt to delete the associated file from the uploads directory
        try:
            logger.debug(f"Deleting file for document {doc_id}")
            # Use the consistent path from settings
            uploads_path = settings.UPLOADS_PATH
            file_paths = os.listdir(uploads_path)
            
            for file_path in file_paths:
                if doc_id in file_path:
                    logger.debug(f"Deleting file: {file_path}")
                    os.remove(os.path.join(uploads_path, file_path))
                    break
        except Exception as e:
            logger.warning(f"Error deleting document file: {e}")
        
        return document
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document {doc_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting document: {str(e)}"
        )