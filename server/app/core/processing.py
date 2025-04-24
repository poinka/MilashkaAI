import io
from fastapi import UploadFile, HTTPException, Depends
from app.db.kuzudb_client import get_db, KuzuDBClient
from app.core.rag_builder import build_rag_graph_from_text
import logging
from datetime import datetime

try:
    import pypdf
except ImportError:
    logging.warning("pypdf not installed. Run: pip install pypdf")
    pypdf = None

try:
    import docx
except ImportError:
    logging.warning("python-docx not installed. Run: pip install python-docx")
    docx = None

try:
    import markdown
except ImportError:
    logging.warning("markdown not installed. Run: pip install markdown")
    markdown = None

async def extract_text_from_file(file: UploadFile) -> str:
    content_type = file.content_type
    filename = file.filename or "unknown"
    logging.info(f"Extracting text from '{filename}' (type: {content_type})")

    try:
        content_bytes = await file.read()
        await file.seek(0)

        if content_type == "application/pdf":
            if not pypdf:
                raise RuntimeError("pypdf required for PDF processing.")
            text = ""
            try:
                pdf_reader = pypdf.PdfReader(io.BytesIO(content_bytes))
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\\n\\n"
            except Exception as e:
                logging.error(f"Error reading PDF '{filename}': {e}")
                raise HTTPException(status_code=400, detail=f"Could not parse PDF: {e}")
            return text.strip()

        elif content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            if not docx:
                raise RuntimeError("python-docx required for DOCX processing.")
            try:
                document = docx.Document(io.BytesIO(content_bytes))
                text = "\\n".join([para.text for para in document.paragraphs])
            except Exception as e:
                logging.error(f"Error reading DOCX '{filename}': {e}")
                raise HTTPException(status_code=400, detail=f"Could not parse DOCX: {e}")
            return text.strip()

        elif content_type == "text/plain":
            try:
                return content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    return content_bytes.decode('latin-1')
                except Exception as e:
                    logging.error(f"Error decoding TXT '{filename}': {e}")
                    raise HTTPException(status_code=400, detail="Could not decode text file.")

        elif content_type == "text/markdown":
            if not markdown:
                raise RuntimeError("markdown required for Markdown processing.")
            try:
                html = markdown.markdown(content_bytes.decode('utf-8'))
                import re
                text = re.sub('<[^>]*>', '', html)
                return text.strip()
            except Exception as e:
                logging.error(f"Error reading Markdown '{filename}': {e}")
                raise HTTPException(status_code=400, detail=f"Could not parse Markdown: {e}")

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")

    except Exception as e:
        logging.error(f"Failed to process file '{filename}': {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Error processing file: {e}")

async def process_uploaded_document(doc_id: str, file: UploadFile, db: KuzuDBClient = Depends(get_db)):
    logging.info(f"Processing document ID: {doc_id}, Filename: {file.filename}")
    # Update status to extracting_text
    now = datetime.utcnow().isoformat()
    try:
        db.execute("""
            MATCH (d:Document {doc_id: $doc_id})
            SET d.status = 'extracting_text', d.updated_at = $updated_at
        """, {"doc_id": doc_id, "updated_at": now})
    except Exception as e:
        logging.error(f"Failed to update status to extracting_text for doc_id {doc_id}: {e}")

    try:
        # Extract Text
        extracted_text = await extract_text_from_file(file)
        if not extracted_text or extracted_text.isspace():
            logging.warning(f"No text extracted from document {doc_id}")
            db.execute("""
                MATCH (d:Document {doc_id: $doc_id})
                SET d.status = 'error', d.updated_at = $updated_at, d.error = 'No text content found'
            """, {"doc_id": doc_id, "updated_at": now})
            return

        logging.info(f"Text extracted for doc_id: {doc_id} (length: {len(extracted_text)})")

        # Update status to building_rag
        db.execute("""
            MATCH (d:Document {doc_id: $doc_id})
            SET d.status = 'building_rag', d.updated_at = $updated_at
        """, {"doc_id": doc_id, "updated_at": now})

        # Build RAG Graph
        await build_rag_graph_from_text(doc_id, file.filename, extracted_text)

        # Update status to indexed
        db.execute("""
            MATCH (d:Document {doc_id: $doc_id})
            SET d.status = 'indexed', d.updated_at = $updated_at, d.error = NULL
        """, {"doc_id": doc_id, "updated_at": now})

        logging.info(f"Processing completed for doc_id: {doc_id}")

    except Exception as e:
        logging.error(f"Processing failed for doc_id {doc_id}: {e}")
        db.execute("""
            MATCH (d:Document {doc_id: $doc_id})
            SET d.status = 'error', d.updated_at = $updated_at, d.error = $error
        """, {"doc_id": doc_id, "updated_at": now, "error": str(e)})
        raise
    finally:
        await file.close()