import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env file if it exists (especially for local development)
load_dotenv()

class Settings(BaseSettings):
    FALKORDB_HOST: str = "localhost"
    FALKORDB_PORT: int = 6379
    FALKORDB_PASSWORD: str | None = None
    GEMMA_MODEL_ID: str = "google/gemma-1.1-2b-it" # Default, can be overridden by .env
    WHISPER_MODEL_ID: str = "openai/whisper-small"
    EMBEDDING_MODEL_ID: str = "sentence-transformers/all-MiniLM-L6-v2"
    # Add other settings as needed, e.g., API keys, logging level

    class Config:
        # If you have a .env file, variables there will override defaults
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = 'ignore' # Ignore extra fields from .env

settings = Settings()
