import logging
from typing import Optional

from sentence_transformers import SentenceTransformer
from transformers import pipeline
from app.core.config import settings
from app.core.llm_wrapper import get_llm

logger = logging.getLogger('app.core.models')

# Global model instances
_embedding_model: Optional[SentenceTransformer] = None
_asr_model = None

def get_embedding_pipeline() -> SentenceTransformer:
    """Get the global embedding model instance"""
    global _embedding_model
    if not _embedding_model:
        logger.info(f"Loading Embedding model: {settings.EMBEDDING_MODEL_NAME}")
        _embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        logger.info("✓ Embedding model loaded successfully")
    return _embedding_model

def get_asr_pipeline():
    """Get the global ASR model instance"""
    global _asr_model
    if not _asr_model:
        logger.info(f"Loading ASR model: {settings.ASR_MODEL_NAME}")
        _asr_model = pipeline("automatic-speech-recognition", 
                            model=settings.ASR_MODEL_NAME, 
                            device="cpu")
        logger.info("✓ ASR model loaded successfully")
    return _asr_model

def load_models():
    """
    Initialize all AI models required by the application.
    Models are loaded lazily when first accessed.
    """
    try:
        # Initialize each model by calling its getter
        logger.info("Initializing AI models...")
        get_llm()
        get_embedding_pipeline()
        get_asr_pipeline()
        logger.info("✓ All AI models initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize models: {str(e)}", exc_info=True)
        raise

def unload_models():
    """
    Clean up model resources.
    """
    global _embedding_model, _asr_model
    logger.info("Unloading AI models...")
    
    try:
        # Explicitly delete model instances
        if _embedding_model:
            del _embedding_model
        if _asr_model:
            del _asr_model
            
        _embedding_model = None
        _asr_model = None
        
        logger.info("✓ Models unloaded successfully")
    except Exception as e:
        logger.error(f"Error during model cleanup: {str(e)}", exc_info=True)
