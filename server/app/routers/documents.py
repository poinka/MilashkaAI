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
from app.db.falkordb_client import get_db_connection

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
            status="processing",
            created_at=now,
            updated_at=now
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
async def list_documents():
    try:
        db = get_db_connection()
        graph_name = "doc_metadata"  # Graph for document metadata
        graph = db.select_graph(graph_name)
        
        # Query documents from the metadata graph
        result = graph.query("""
            MATCH (d:Document)
            RETURN d.doc_id AS doc_id,
                   d.filename AS filename,
                   d.status AS status,
                   d.created_at AS created_at,
                   d.updated_at AS updated_at,
                   d.error AS error
            ORDER BY d.created_at DESC
        """)
        
        documents = []
        for record in result.result_set:
            try:
                created_at = datetime.fromisoformat(record[3]) if record[3] else datetime.utcnow()
                updated_at = datetime.fromisoformat(record[4]) if record[4] else datetime.utcnow()
                
                doc = DocumentMetadata(
                    doc_id=record[0],
                    filename=record[1],
                    status=record[2],
                    created_at=created_at,
                    updated_at=updated_at,
                    error=record[5]
                )
                documents.append(doc)
            except Exception as e:
                logging.error(f"Error parsing document record: {e}")
        
        return documents
    except Exception as e:
        logging.error(f"Error listing documents: {e}")
        return []

@router.get("/{doc_id}", 
    response_model=DocumentMetadata,
    summary="Get document status")
async def get_document_status(doc_id: str):
    db = get_db_connection()
    
    try:
        # Get document from the metadata graph
        graph_name = "doc_metadata"
        graph = db.select_graph(graph_name)
        
        result = graph.query("""
            MATCH (d:Document {doc_id: $doc_id})
            RETURN d.doc_id AS doc_id,
                   d.filename AS filename,
                   d.status AS status,
                   d.created_at AS created_at,
                   d.updated_at AS updated_at,
                   d.error AS error
        """, params={"doc_id": doc_id})
        
        if not result.result_set:
            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )
            
        record = result.result_set[0]
        created_at = datetime.fromisoformat(record[3]) if record[3] else datetime.utcnow()
        updated_at = datetime.fromisoformat(record[4]) if record[4] else datetime.utcnow()
        
        document = DocumentMetadata(
            doc_id=record[0],
            filename=record[1],
            status=record[2],
            created_at=created_at,
            updated_at=updated_at,
            error=record[5]
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
    db = get_db_connection()
    
    try:
        # First get the document to return its data
        document = await get_document_status(doc_id)
        
        # Delete from the document-specific graph
        doc_graph_name = f"doc_{doc_id}"
        try:
            db.delete_graph(doc_graph_name)
        except Exception as e:
            logging.warning(f"Error deleting document graph {doc_graph_name}: {e}")
        
        # Delete from the metadata graph
        meta_graph = db.select_graph("doc_metadata")
        meta_graph.query("""
            MATCH (d:Document {doc_id: $doc_id})
            DETACH DELETE d
        """, params={"doc_id": doc_id})
        
        # Clean up from global index - delete vectors related to this document
        try:
            db.execute_command(
                f"FT.SEARCH milashka_chunk_embedding_idx '@doc_id:{{{doc_id}}}'",
                "LIMIT", "0", "NOCONTENT"
            )
        except Exception as e:
            logging.warning(f"Error cleaning up document vectors: {e}")
        
        # Try to delete the original file if it exists
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
