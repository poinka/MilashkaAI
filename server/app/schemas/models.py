from pydantic import BaseModel, Field
from typing import List, Optional

# --- Document Schemas ---
class DocumentUploadRequest(BaseModel):
    # FastAPI handles file uploads separately, so we might not need file content here.
    # We might need metadata though.
    filename: str
    # content_type: str # Provided by FastAPI UploadFile

class DocumentMetadata(BaseModel):
    doc_id: str = Field(..., description="Unique identifier for the document")
    filename: str
    status: str = Field(default="processing", description="Status like processing, indexed, error")
    error_message: Optional[str] = None

# --- Completion Schemas ---
class CompletionRequest(BaseModel):
    current_text: str = Field(..., description="The text preceding the cursor")
    full_document_context: Optional[str] = Field(None, description="Optional full document context")
    language: str = Field(default="ru", description="Language for completion (e.g., 'ru', 'en')")
    # Add other parameters like max_tokens, temperature if needed

class CompletionResponse(BaseModel):
    suggestion: str = Field(..., description="The suggested text completion")

# --- Voice Schemas ---
class VoiceInputRequest(BaseModel):
    # Audio data will likely be sent as a file upload
    language: str = Field(default="ru", description="Language of the speech (e.g., 'ru', 'en')")

class VoiceTranscriptionResponse(BaseModel):
    raw_transcription: str
    formatted_transcription: Optional[str] = None # Formatted by Gemma

class StructuredRequirement(BaseModel):
    actor: Optional[str] = None
    action: Optional[str] = None
    object: Optional[str] = None
    result: Optional[str] = None

class VoiceToRequirementResponse(BaseModel):
    structured_requirement: StructuredRequirement
    original_transcription: str

# --- Editing Schemas ---
class EditRequest(BaseModel):
    selected_text: str = Field(..., description="The text selected by the user")
    prompt: str = Field(..., description="User's instruction for editing (text or voice transcription)")
    language: str = Field(default="ru", description="Language for editing (e.g., 'ru', 'en')")

class EditResponse(BaseModel):
    edited_text: str = Field(..., description="The resulting edited text")

# --- RAG Schemas ---
class RagQueryRequest(BaseModel):
    query_text: str
    top_k: int = 5 # Number of relevant chunks to retrieve

class RagChunk(BaseModel):
    text: str
    score: float
    metadata: Optional[dict] = None # e.g., source document, location

class RagQueryResponse(BaseModel):
    relevant_chunks: List[RagChunk]

# --- General Schemas ---
class StatusResponse(BaseModel):
    status: str
    message: Optional[str] = None
