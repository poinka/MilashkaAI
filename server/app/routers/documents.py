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

router = APIRouter(
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse}
    }
)

async def save_upload_file(file: UploadFile) -> str:
    """Save uploaded file and return the saved path"""
    # Create uploads directory if it doesn't exist
    os.makedirs("uploads", exist_ok=True)
    
    # Generate unique filename
    ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join("uploads", unique_filename)
    
    # Save file
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
    # Validate file size
    if file.size and file.size > settings.MAX_DOCUMENT_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds maximum limit of {settings.MAX_DOCUMENT_SIZE / 1024 / 1024}MB"
        )
    
    # Validate file type
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in settings.SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Supported formats: {', '.join(settings.SUPPORTED_FORMATS)}"
        )

    try:
        # Save file
        file_path = await save_upload_file(file)
        
        # Create document metadata
        doc_id = str(uuid.uuid4())
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

        # Add document processing to background tasks
        background_tasks.add_task(
            build_rag_graph_from_text, 
            doc_id=doc_id, 
            filename=file.filename, 
            text="Текст извлеченный из файла..." 
        )

        return metadata

    except Exception as e:
        # Clean up file if saved
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
    response_model=List[DocumentMetadata],
    summary="List all uploaded documents")

def list_documents():
    """List all documents stored in the Document table."""
    try:
        conn: Connection = get_db_connection()
        
        # Ensure Document table exists
        conn.execute(f"""
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
        
        # Query documents
        result = conn.execute(f"""
            MATCH (d:Document)
            RETURN d.doc_id, d.filename, d.processed_at, d.status, d.created_at, d.updated_at
        """)
        documents = []
        while result.has_next():
            row = result.get_next()
            documents.append({
                "doc_id": row[0],
                "filename": row[1],
                "processed_at": row[2],
                "status": row[3] if row[3] is not None else "indexed",
                "created_at": row[4] if row[4] is not None else datetime.now().isoformat(),
                "updated_at": row[5] if row[5] is not None else datetime.now().isoformat(),
                'error': None
            })
        return documents
    except Exception as e:
        logging.error(f"Error listing documents: {e}")
        return []

@router.get("/{doc_id}", 
    response_model=DocumentMetadata,
    summary="Get document status")
async def get_document_status(doc_id: str):
    """Retrieve metadata for a specific document."""
    try:
        conn = get_db_connection()
        
        result = conn.execute(f"""
            MATCH (d:Document {{doc_id: $doc_id}})
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
            updated_at=datetime.fromisoformat(record[5]) if record[5] else datetime.utcnow(),
            error=None
        )
        
        return document
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error retrieving document {doc_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving document: {str(e)}"
        )

@router.delete("/{doc_id}",
    response_model=DocumentMetadata,
    summary="Delete a document")
async def delete_document(doc_id: str):
    """Delete a document and its associated chunks."""
    try:
        conn = get_db_connection()
        
        document = await get_document_status(doc_id)
        
        conn.execute(f"""
            MATCH (d:Document {{doc_id: $doc_id}})
            OPTIONAL MATCH (d)-[:Contains]->(c:Chunk)
            DETACH DELETE d, c
        """, {"doc_id": doc_id})
        
        try:
            file_paths = os.listdir("uploads")
            for file_path in file_paths:
                if doc_id in file_path:
                    os.remove(os.path.join("uploads", file_path))
                    break
        except Exception as e:
            logging.warning(f"Error deleting document file: {e}")
        
        return document
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error deleting document {doc_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting document: {str(e)}"
        )