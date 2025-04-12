from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from typing import List
import uuid

from app.schemas.models import DocumentMetadata, StatusResponse
# Placeholder for actual processing logic
from app.core.processing import process_uploaded_document
from app.db.falkordb_client import get_db_connection # Assuming synchronous for now
from falkordb import FalkorDB

router = APIRouter()

# In-memory storage for demo purposes. Replace with proper DB persistence.
document_status_db = {}

@router.post("/upload", response_model=DocumentMetadata)
async def upload_document(
    file: UploadFile = File(...),
    # db: FalkorDB = Depends(get_db_connection) # Inject DB dependency
):
    """
    Receives a document file (pdf, docx, txt, md), assigns a unique ID,
    and triggers background processing.
    """
    allowed_content_types = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", # docx
        "text/plain",
        "text/markdown"
    ]
    if file.content_type not in allowed_content_types:
        raise HTTPException(status_code=400, detail=f"Invalid file type: {file.content_type}. Allowed types: pdf, docx, txt, md")

    doc_id = str(uuid.uuid4())
    filename = file.filename or f"upload_{doc_id}"
    print(f"Received file: {filename}, type: {file.content_type}, assigning ID: {doc_id}")

    # Store initial metadata (in-memory for now)
    metadata = DocumentMetadata(doc_id=doc_id, filename=filename, status="received")
    document_status_db[doc_id] = metadata.dict() # Store as dict

    try:
        # --- Trigger Background Processing ---
        # In a real application, use a task queue like Celery or FastAPI's BackgroundTasks
        # For simplicity here, we call the processing function directly (can block)
        # Consider making process_uploaded_document async if it involves I/O
        print(f"Starting processing for doc_id: {doc_id}")
        # await process_uploaded_document(doc_id, file, db) # Pass db connection
        await process_uploaded_document(doc_id, file) # Simplified call without DB for now
        print(f"Finished processing trigger for doc_id: {doc_id}")
        # Update status after triggering (or after completion if synchronous)
        document_status_db[doc_id]["status"] = "processing" # Or "indexed" if sync and successful
        metadata.status = document_status_db[doc_id]["status"]

    except Exception as e:
        print(f"Error triggering processing for {doc_id}: {e}")
        document_status_db[doc_id]["status"] = "error"
        document_status_db[doc_id]["error_message"] = str(e)
        metadata.status = "error"
        metadata.error_message = str(e)
        # Depending on the error, might want to raise HTTPException or just return error status
        # raise HTTPException(status_code=500, detail=f"Failed to start processing: {e}")

    return metadata

@router.get("/status/{doc_id}", response_model=DocumentMetadata)
async def get_document_status(doc_id: str):
    """
    Retrieves the processing status of a previously uploaded document.
    """
    status_info = document_status_db.get(doc_id)
    if not status_info:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentMetadata(**status_info)

@router.get("/", response_model=List[DocumentMetadata])
async def list_documents():
    """
    Lists all documents known to the system (metadata only).
    """
    return [DocumentMetadata(**meta) for meta in document_status_db.values()]

# Placeholder for delete endpoint
@router.delete("/{doc_id}", response_model=StatusResponse)
async def delete_document(doc_id: str):
    """
    Deletes a document and its associated data (from DB, RAG, etc.).
    (Implementation needed)
    """
    if doc_id in document_status_db:
        del document_status_db[doc_id]
        # Add logic to delete from FalkorDB graph here
        print(f"Deleted document metadata for {doc_id} (in-memory). DB deletion needed.")
        return StatusResponse(status="success", message="Document deleted (metadata only)")
    else:
        raise HTTPException(status_code=404, detail="Document not found")
