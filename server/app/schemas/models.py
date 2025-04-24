from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime

class CompletionRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    language: str = Field(default="ru", pattern="^(ru|en)$")

class CompletionResponse(BaseModel):
    completion: str
    metadata: Optional[Dict[str, Any]] = None

class CompletionStreamResponse(BaseModel):
    token: str
    is_final: bool = False
    metadata: Optional[Dict[str, Any]] = None

class EditRequest(BaseModel):
    selected_text: str = Field(..., min_length=1, max_length=10000)
    prompt: str = Field(..., min_length=1, max_length=1000)
    language: str = Field(default="ru", pattern="^(ru|en)$")

class EditResponse(BaseModel):
    edited_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    alternatives: Optional[List[str]] = None
    warning: Optional[str] = None

class DocumentMetadata(BaseModel):
    doc_id: str
    filename: str
    status: str = Field(pattern="^(processing|indexed|error)$")
    created_at: datetime
    updated_at: datetime
    error: Optional[str] = None

class VoiceTranscriptionRequest(BaseModel):
    language: str = Field(default="ru", pattern="^(ru|en)$")

    @validator('language')
    def validate_language(cls, v):
        if v.lower() not in ['ru', 'en']:
            raise ValueError('Language must be either "ru" or "en"')
        return v.lower()

class VoiceTranscriptionResponse(BaseModel):
    text: str
    is_final: bool = True
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)

class RequirementComponents(BaseModel):
    actor: str
    action: str
    object: str
    result: str

class RequirementExtractionResponse(BaseModel):
    components: RequirementComponents
    confidence: float = Field(ge=0.0, le=1.0)
    raw_text: str
