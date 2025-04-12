from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline, BitsAndBytesConfig
import torch
from app.core.config import settings
import logging

# Global variables to hold models and tokenizers
# In a production scenario, consider a more robust class-based approach or dependency injection
llm_model = None
llm_tokenizer = None
embedding_pipeline = None
asr_pipeline = None

def load_models():
    """Loads all required AI models."""
    global llm_model, llm_tokenizer, embedding_pipeline, asr_pipeline
    print("Loading AI models...")

    # --- Load Gemma ---
    try:
        print(f"Loading LLM: {settings.GEMMA_MODEL_ID}")
        # Configure quantization (4-bit as requested)
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4", # Or "fp4"
            bnb_4bit_compute_dtype=torch.bfloat16 # Or torch.float16 depending on GPU
            # bnb_4bit_use_double_quant=True, # Optional
        )

        llm_tokenizer = AutoTokenizer.from_pretrained(settings.GEMMA_MODEL_ID)
        llm_model = AutoModelForCausalLM.from_pretrained(
            settings.GEMMA_MODEL_ID,
            quantization_config=quantization_config,
            # torch_dtype=torch.bfloat16, # Match compute_dtype if possible
            device_map="auto", # Automatically distribute across available GPUs/CPU
            # low_cpu_mem_usage=True, # Can help on systems with limited CPU RAM
            trust_remote_code=True # If required by the specific model version
        )
        print("Gemma model loaded successfully.")
    except Exception as e:
        logging.error(f"Failed to load Gemma model: {e}", exc_info=True)
        # Decide how to handle: raise error, fallback, etc.
        raise RuntimeError(f"Failed to load Gemma model: {e}") from e

    # --- Load Embedding Model ---
    try:
        print(f"Loading Embedding model: {settings.EMBEDDING_MODEL_ID}")
        # Using sentence-transformers pipeline for simplicity
        # Ensure 'sentence-transformers' is installed if using this approach
        # Or use a standard transformers pipeline if preferred
        from sentence_transformers import SentenceTransformer # Lazy import
        embedding_pipeline = SentenceTransformer(
            settings.EMBEDDING_MODEL_ID,
            device="cuda" if torch.cuda.is_available() else "cpu"
        )
        # Perform a dummy encoding to ensure it's loaded
        _ = embedding_pipeline.encode(["test"])
        print("Embedding model loaded successfully.")
    except ImportError:
         logging.error("SentenceTransformers library not found. Please install it: pip install sentence-transformers")
         raise RuntimeError("SentenceTransformers library not found.")
    except Exception as e:
        logging.error(f"Failed to load Embedding model: {e}", exc_info=True)
        raise RuntimeError(f"Failed to load Embedding model: {e}") from e

    # --- Load Whisper ---
    try:
        print(f"Loading ASR model: {settings.WHISPER_MODEL_ID}")
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

        # Use transformers pipeline for ASR
        asr_pipeline = pipeline(
            "automatic-speech-recognition",
            model=settings.WHISPER_MODEL_ID,
            torch_dtype=torch_dtype,
            device=device,
        )
        # Optional: Optimize Whisper with Flash Attention 2 if available and compatible
        # try:
        #     asr_pipeline.model = asr_pipeline.model.to_bettertransformer()
        #     print("Optimized Whisper with BetterTransformer (if applicable).")
        # except Exception as optim_e:
        #     print(f"Could not optimize Whisper: {optim_e}")

        print("Whisper model loaded successfully.")
    except Exception as e:
        logging.error(f"Failed to load Whisper model: {e}", exc_info=True)
        raise RuntimeError(f"Failed to load Whisper model: {e}") from e

    print("All AI models loaded.")

def unload_models():
    """Unloads models to free up memory (if necessary)."""
    global llm_model, llm_tokenizer, embedding_pipeline, asr_pipeline
    print("Unloading AI models...")
    # Explicitly delete models and clear CUDA cache if using GPU
    del llm_model
    del llm_tokenizer
    del embedding_pipeline
    del asr_pipeline
    llm_model = None
    llm_tokenizer = None
    embedding_pipeline = None
    asr_pipeline = None
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("AI models unloaded.")

# --- Accessor functions ---
# These functions provide access to the loaded models.
# Consider using dependency injection in FastAPI instead of global accessors.

def get_llm():
    if not llm_model or not llm_tokenizer:
        raise RuntimeError("LLM model not loaded. Call load_models() first.")
    return llm_model, llm_tokenizer

def get_embedding_pipeline():
    if not embedding_pipeline:
        raise RuntimeError("Embedding model not loaded. Call load_models() first.")
    return embedding_pipeline

def get_asr_pipeline():
    if not asr_pipeline:
        raise RuntimeError("ASR model not loaded. Call load_models() first.")
    return asr_pipeline