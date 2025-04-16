from transformers import pipeline
import torch
from app.core.config import settings
import logging

# llama-cpp-python for GGUF LLM
from llama_cpp import Llama

llm_model = None
embedding_pipeline = None
asr_pipeline = None


def load_models():
    """Loads all required AI models."""
    global llm_model, embedding_pipeline, asr_pipeline
    print("Loading AI models...")

    # --- Load Llama.cpp GGUF LLM ---
    try:
        print(f"Loading LLM (llama.cpp): {settings.LLAMA_GGUF_PATH}")
        llm_model = Llama(
            model_path=settings.LLAMA_GGUF_PATH,
            n_ctx=4096,  # adjust as needed
            n_threads=4, # adjust as needed
            n_gpu_layers=20 # adjust for Metal
        )
        print("Llama.cpp LLM loaded successfully.")
    except Exception as e:
        logging.error(f"Failed to load Llama.cpp LLM: {e}", exc_info=True)
        raise RuntimeError(f"Failed to load Llama.cpp LLM: {e}") from e

    # --- Load Embedding Model ---
    try:
        print(f"Loading Embedding model: {settings.EMBEDDING_MODEL_ID}")
        from sentence_transformers import SentenceTransformer
        embedding_pipeline = SentenceTransformer(
            settings.EMBEDDING_MODEL_ID,
            device="cuda" if torch.cuda.is_available() else "cpu"
        )
        _ = embedding_pipeline.encode(["test"])
        print("Embedding model loaded successfully.")
    except ImportError:
        logging.error("SentenceTransformers library not found. Please install it: pip install sentence-transformers")
        raise RuntimeError("SentenceTransformers library not found.")
    except Exception as e:
        logging.error(f"Failed to load Embedding model: {e}", exc_info=True)
        raise RuntimeError(f"Failed to load Embedding model: {e}") from e

    # --- Load Whisper ASR ---
    try:
        print(f"Loading ASR model: {settings.WHISPER_MODEL_ID}")
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        asr_pipeline = pipeline(
            "automatic-speech-recognition",
            model=settings.WHISPER_MODEL_ID,
            torch_dtype=torch_dtype,
            device=device,
        )
        print("Whisper model loaded successfully.")
    except Exception as e:
        logging.error(f"Failed to load Whisper model: {e}", exc_info=True)
        raise RuntimeError(f"Failed to load Whisper model: {e}") from e

    print("All AI models loaded.")

def unload_models():
    """Unloads models to free up memory (if necessary)."""
    global llm_model, embedding_pipeline, asr_pipeline
    print("Unloading AI models...")
    # Explicitly delete models and clear CUDA cache if using GPU
    del llm_model
    del embedding_pipeline
    del asr_pipeline
    llm_model = None
    embedding_pipeline = None
    asr_pipeline = None
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("AI models unloaded.")

# --- Accessor functions ---
# These functions provide access to the loaded models.
# Consider using dependency injection in FastAPI instead of global accessors.

def get_llm():
    if not llm_model:
        raise RuntimeError("LLM model not loaded. Call load_models() first.")
    return llm_model

def get_embedding_pipeline():
    if not embedding_pipeline:
        raise RuntimeError("Embedding model not loaded. Call load_models() first.")
    return embedding_pipeline

def get_asr_pipeline():
    if not asr_pipeline:
        raise RuntimeError("ASR model not loaded. Call load_models() first.")
    return asr_pipeline