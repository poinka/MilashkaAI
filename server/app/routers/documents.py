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
from app.middleware import verify_api_key
from app.core.rag_builder import process_document
from app.db.falkordb_client import get_db_connection

router = APIRouter(
    dependencies=[Depends(verify_api_key)],
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
            status="processing",
            created_at=now,
            updated_at=now
        )

        # Add document processing to background tasks
        background_tasks.add_task(
            process_document,
            file_path,
            doc_id,
            get_db_connection()
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
async def list_documents():
    db = get_db_connection()
    # Implementation to fetch document list from FalkorDB
    # This is a placeholder - actual implementation needed
    documents = []  # Fetch from database
    return documents

@router.get("/{doc_id}", 
    response_model=DocumentMetadata,
    summary="Get document status")
async def get_document_status(doc_id: str):
    db = get_db_connection()
    # Implementation to fetch document status from FalkorDB
    # This is a placeholder - actual implementation needed
    document = None  # Fetch from database
    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found"
        )
    return document

@router.delete("/{doc_id}",
    response_model=DocumentMetadata,
    summary="Delete a document")
async def delete_document(doc_id: str):
    db = get_db_connection()
    # Implementation to delete document from FalkorDB
    # This is a placeholder - actual implementation needed
    document = None  # Fetch from database
    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found"
        )
    # Delete document and its vectors
    return document
