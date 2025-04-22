from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Path settings - consolidated to a single data directory
    DATA_ROOT: str = "/data"
    KUZUDB_PATH: str = os.path.join(DATA_ROOT, "kuzu_db")
    UPLOADS_PATH: str = "/app/uploads"  # Matches docker-compose volume mount

    # Model settings
    YANDEX_MODEL_ID: str = "yandex/YandexGPT-5-Lite-8B-instruct"
    GEMMA_MODEL_ID: str = "google/gemma-3-4b-it-qat-q4_0-gguf"
    WHISPER_MODEL_ID: str = "openai/whisper-small"
    EMBEDDING_MODEL_ID: str = "sentence-transformers/all-MiniLM-L6-v2"
    
    # Performance settings
    BATCH_SIZE: int = 32
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB
    CHUNK_SIZE: int = 8192
    MAX_INPUT_LENGTH: int = 4096 # Max tokens for LLM input
    MAX_OUTPUT_LENGTH: int = 512 # Max tokens for LLM output
    
    # RAG settings
    RAG_TOP_K: int = 5
    RAG_SIMILARITY_THRESHOLD: float = 0.7
    VECTOR_DIMENSION: int = 768
    
    # Document processing
    MAX_DOCUMENT_SIZE: int = 50 * 1024 * 1024  # 50MB
    SUPPORTED_FORMATS: List[str] = [".pdf", ".docx", ".txt", ".md"]
    
    # Voice processing
    MAX_AUDIO_DURATION: int = 60  # Seconds
    SUPPORTED_AUDIO_FORMATS: List[str] = ["audio/webm", "audio/wav", "audio/mp3"]
    # Add path to GGUF model for llama.cpp
    LLAMA_GGUF_PATH: str = "/models/gemma-3-4b-it-q4_0.gguf"

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        env_prefix='',  # pick up env vars as-is
    )

settings = Settings()
