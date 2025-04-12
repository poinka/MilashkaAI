from pydantic import BaseModel
from typing import Any, Optional, Dict

class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class ValidationError(BaseModel):
    loc: tuple
    msg: str
    type: str

class HTTPValidationError(BaseModel):
    detail: list[ValidationError]
