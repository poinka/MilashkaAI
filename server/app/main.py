from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.core.config import settings # Import settings
# Import routers (assuming they exist, we'll create them later)
from app.routers import documents, completion, voice, editing, rag
from app.db.falkordb_client import get_db_connection, close_db_connection
# Placeholder for model loading - will be implemented in core/models.py
from app.core.models import load_models, unload_models

# Define lifespan context manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load models and connect to DB
    print("Application startup...")
    try:
        # Load AI models (Gemma, Whisper, Embeddings)
        load_models() # This function needs to be implemented in core/models.py
        print("AI models loaded.")
        # Establish DB connection
        get_db_connection() # This connects synchronously, adjust if async client is used
        print("Database connection established.")
    except Exception as e:
        print(f"Error during startup: {e}")
        # Decide how to handle startup errors (e.g., exit, log)
        raise # Re-raise the exception to potentially stop the app

    yield # Application runs here

    # Shutdown: Unload models and close DB connection
    print("Application shutdown...")
    close_db_connection()
    unload_models() # This function needs to be implemented in core/models.py
    print("Resources cleaned up.")

# Create FastAPI app instance with lifespan manager
app = FastAPI(
    title="MilashkaAI Server",
    description="Backend API for the MilashkaAI text assistant browser extension.",
    version="0.1.0",
    lifespan=lifespan
)

# Include API routers
app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(completion.router, prefix="/api/v1/completion", tags=["Completion"])
app.include_router(voice.router, prefix="/api/v1/voice", tags=["Voice"])
app.include_router(editing.router, prefix="/api/v1/editing", tags=["Editing"])
app.include_router(rag.router, prefix="/api/v1/rag", tags=["RAG"])

# Basic root endpoint for health check
@app.get("/", tags=["Health Check"])
async def read_root():
    return {"message": f"Welcome to MilashkaAI API - Version {app.version}"}

# Placeholder: Add CORS middleware if the extension and server run on different origins
# from fastapi.middleware.cors import CORSMiddleware
# origins = [
#     "moz-extension://...", # Add your extension's origin
#     "chrome-extension://...", # Add your extension's origin
#     # "http://localhost:3000", # Example for local frontend dev
# ]
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )
