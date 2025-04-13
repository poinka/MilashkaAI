from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.routers import documents, completion, voice, editing, rag, feedback
from app.db.falkordb_client import get_db_connection, close_db_connection
from app.core.models import load_models, unload_models

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        load_models()
        get_db_connection()
        yield
    finally:
        # Cleanup
        close_db_connection()
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

# Include routers
app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(completion.router, prefix="/api/v1/completion", tags=["Completion"])
app.include_router(voice.router, prefix="/api/v1/voice", tags=["Voice"])
app.include_router(editing.router, prefix="/api/v1/editing", tags=["Editing"])
app.include_router(rag.router, prefix="/api/v1/rag", tags=["RAG"])
app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["Feedback"])

@app.get("/")
async def read_root():
    return {"message": "MilashkaAI API"}
