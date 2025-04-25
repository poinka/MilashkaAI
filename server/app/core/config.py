from pathlib import Path
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Project metadata
    PROJECT_NAME: str = "Комплит"
    VERSION: str = "1.0.0"
    
    # API configuration
    API_PREFIX: str = "/api/v1"
    
    # Database configuration
    KUZUDB_PATH: str = os.getenv("KUZUDB_PATH", "/data/kuzu/db")
    UPLOADS_PATH: str = os.getenv("UPLOADS_PATH", "/app/uploads")
    
    # Logging configuration
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "[%(levelname)s] %(name)s: %(message)s"
    LOG_FILE: str = "logs/app.log"
    LOG_MAX_SIZE: int = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT: int = 5
    
    # Model paths and settings
    LLM_MODEL_PATH: str = os.getenv("LLM_MODEL_PATH", "/models/gemma-3-4b-it-q4_0.gguf")
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    ASR_MODEL_NAME: str = "openai/whisper-small"
    
    # RAG settings
    RAG_TOP_K: int = 3
    RAG_SIMILARITY_THRESHOLD: float = 0.7
    
    # Document settings
    MAX_DOCUMENT_SIZE: int = 20 * 1024 * 1024  # 20MB
    SUPPORTED_FORMATS: list = [".pdf", ".docx", ".txt", ".md"]
    
    class Config:
        env_file = ".env"

settings = Settings()
