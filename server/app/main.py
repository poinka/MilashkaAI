import logging
import sys
import faulthandler; 

faulthandler.enable()

# Set up logging at the start of the file
from app.core.logging_config import setup_logging
logger = setup_logging()

# Suppress third-party logs
import logging
for logger_name in [
    'uvicorn.access',
    'uvicorn.error',
    'sentence_transformers',
    'torch',
    'tqdm',
    'transformers',
    'spacy',
    'llama_cpp'
]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.routers import documents, completion, voice, editing, rag, feedback
from app.db.kuzudb_client import get_db_connection, close_db_connection  # Updated import
from app.core.models import load_models, unload_models

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        load_models()
        get_db_connection()  # Initialize KuZuDB connection
        yield
    finally:
        # Cleanup
        close_db_connection()  # Close KuZuDB connection
        unload_models()

app = FastAPI(
    title="MilashkaAI Server",
    description="Backend API for MilashkaAI browser extension",
    version="1.0.0",
    lifespan=lifespan
)

# Simple CORS middleware for extension communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for hackathon
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(completion.router, prefix="/api/v1/completion", tags=["completion"])
app.include_router(voice.router, prefix="/api/v1/voice", tags=["voice"])
app.include_router(editing.router, prefix="/api/v1/editing", tags=["editing"])
app.include_router(rag.router, prefix="/api/v1/rag", tags=["rag"])
app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["feedback"])

@app.get("/")
async def read_root():
    return {"message": "MilashkaAI API"}
