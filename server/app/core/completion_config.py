# Constants (moved to config.py)
from dataclasses import dataclass
from typing import Optional

@dataclass
class CompletionConfig:
    MAX_INPUT_LENGTH: int = 1024
    MAX_NEW_TOKENS: int = 50  # Reduced for better auto-completion (was 100)
    RAG_TOP_K: int = 3
    STREAM_BATCH_SIZE: int = 1  # Log every token for debugging
    TEMPERATURE: float = 0.3  # Reduced for more predictable completions (was 0.7)
    RAG_MAX_QUERY_LENGTH: int = 512
    DEBUG_MODE: bool = True  # Enable detailed logging

class CompletionPrompts:
    # Enhanced prompt specifically for auto-completion
    SYSTEM_TEMPLATE = "You are an auto-completion AI. Predict and continue the text in {language} with the most natural completion. {streaming_guide}"
    SYSTEM_STREAMING_GUIDE = "Provide only the completion text that follows naturally. Do not repeat any part of the input."
    USER_TEMPLATE = "Auto-complete this text{streaming_note}: {text}"
    USER_STREAMING_NOTE = ". Return ONLY the completion, not the original text"
