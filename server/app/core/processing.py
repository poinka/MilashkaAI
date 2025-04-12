import io
from fastapi import UploadFile, HTTPException
import logging

# Import parsing libraries (ensure they are in requirements.txt)
try:
    import pypdf
except ImportError:
    logging.warning("pypdf not installed. PDF processing will fail. Run: pip install pypdf")
    pypdf = None

try:
    import docx
except ImportError:
    logging.warning("python-docx not installed. DOCX processing will fail. Run: pip install python-docx")
    docx = None

try:
    import markdown
except ImportError:
    logging.warning("markdown not installed. Markdown processing will fail. Run: pip install markdown")
    markdown = None


async def extract_text_from_file(file: UploadFile) -> str:
    """Extracts plain text content from various document types."""
    content_type = file.content_type
    filename = file.filename or "unknown"
    logging.info(f"Extracting text from '{filename}' (type: {content_type})")

    try:
        content_bytes = await file.read()
        await file.seek(0) # Reset file pointer in case it's needed again

        if content_type == "application/pdf":
            if not pypdf:
                raise RuntimeError("pypdf library is required for PDF processing but not installed.")
            text = ""
            try:
                pdf_reader = pypdf.PdfReader(io.BytesIO(content_bytes))
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\\n\\n" # Add newline between pages
            except Exception as e:
                logging.error(f"Error reading PDF '{filename}': {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=f"Could not parse PDF file: {e}")
            return text.strip()

        elif content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            if not docx:
                raise RuntimeError("python-docx library is required for DOCX processing but not installed.")
            try:
                document = docx.Document(io.BytesIO(content_bytes))
                text = "\\n".join([para.text for para in document.paragraphs])
            except Exception as e:
                logging.error(f"Error reading DOCX '{filename}': {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=f"Could not parse DOCX file: {e}")
            return text.strip()

        elif content_type == "text/plain":
            try:
                return content_bytes.decode('utf-8') # Assume UTF-8 for plain text
            except UnicodeDecodeError:
                try:
                    # Try another common encoding if UTF-8 fails
                    return content_bytes.decode('latin-1')
                except Exception as e:
                     logging.error(f"Error decoding TXT '{filename}': {e}", exc_info=True)
                     raise HTTPException(status_code=400, detail=f"Could not decode plain text file.")

        elif content_type == "text/markdown":
             if not markdown:
                raise RuntimeError("markdown library is required for Markdown processing but not installed.")
             try:
                # Convert markdown to HTML, then strip tags for plain text
                # This is a basic approach; more sophisticated text extraction might be needed
                html = markdown.markdown(content_bytes.decode('utf-8'))
                # Basic HTML tag stripping (consider using BeautifulSoup for robustness)
                import re
                text = re.sub('<[^>]*>', '', html)
                return text.strip()
             except Exception as e:
                logging.error(f"Error reading Markdown '{filename}': {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=f"Could not parse Markdown file: {e}")

        else:
            # Should have been caught by the router, but double-check
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")

    except Exception as e:
        logging.error(f"Failed to process file '{filename}': {e}", exc_info=True)
        # Re-raise specific HTTP exceptions or a generic one
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Error processing file: {e}")


# This is the function called by the router. It orchestrates the processing.
# It needs access to the RAG builder logic.
from .rag_builder import build_rag_graph_from_text # Import after definition or handle circularity

async def process_uploaded_document(doc_id: str, file: UploadFile):
    """Orchestrates the document processing pipeline:
    1. Extract text from the uploaded file.
    2. Build the RAG graph using the extracted text.
    3. Update document status (handled partially in router, refine here).
    """
    # In-memory status update (replace with DB update)
    from app.routers.documents import document_status_db # Temporary access for demo

    try:
        logging.info(f"Processing document ID: {doc_id}, Filename: {file.filename}")
        document_status_db[doc_id]["status"] = "extracting_text"

        # 1. Extract Text
        extracted_text = await extract_text_from_file(file)
        if not extracted_text or extracted_text.isspace():
             logging.warning(f"No text extracted from document {doc_id}")
             document_status_db[doc_id]["status"] = "error"
             document_status_db[doc_id]["error_message"] = "No text content found in the document."
             return # Stop processing if no text

        logging.info(f"Text extracted successfully for doc_id: {doc_id} (length: {len(extracted_text)})")
        document_status_db[doc_id]["status"] = "building_rag"

        # 2. Build RAG Graph (This function needs the DB connection and models)
        # Consider passing db connection and models explicitly if not using globals/DI
        await build_rag_graph_from_text(doc_id, file.filename, extracted_text)

        logging.info(f"RAG graph building initiated/completed for doc_id: {doc_id}")
        document_status_db[doc_id]["status"] = "indexed" # Update status on success
        document_status_db[doc_id]["error_message"] = None

    except Exception as e:
        logging.error(f"Processing failed for doc_id {doc_id}: {e}", exc_info=True)
        document_status_db[doc_id]["status"] = "error"
        document_status_db[doc_id]["error_message"] = str(e)
        # Optionally raise exception to signal failure upstream
        # raise e
    finally:
        # Ensure file is closed if not already
        try:
            await file.close()
        except Exception:
            pass # Ignore errors on close
