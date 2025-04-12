from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
import asyncio
from typing import AsyncGenerator

from app.core.config import settings
from app.schemas.models import (
    VoiceTranscriptionRequest,
    VoiceTranscriptionResponse,
    RequirementExtractionResponse
)
from app.schemas.errors import ErrorResponse
from app.middleware import verify_api_key
from app.core.voice import (
    transcribe_audio,
    format_transcription,
    extract_requirements,
    stream_transcription
)

router = APIRouter(
    dependencies=[Depends(verify_api_key)],
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse}
    }
)

@router.post("/transcribe",
    response_model=VoiceTranscriptionResponse,
    summary="Transcribe audio file")
async def transcribe_voice(
    file: UploadFile = File(...),
    request: VoiceTranscriptionRequest = Depends()
):
    if not file.content_type.startswith('audio/'):
        raise HTTPException(
            status_code=400,
            detail="File must be an audio file"
        )

    try:
        # Read audio file
        audio_bytes = await file.read()
        
        # Transcribe
        raw_transcription = await transcribe_audio(
            audio_bytes,
            request.language
        )
        
        # Format transcription
        formatted_text = await format_transcription(
            raw_transcription,
            request.language
        )
        
        return VoiceTranscriptionResponse(
            text=formatted_text,
            is_final=True
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Transcription failed: {str(e)}"
        )

@router.websocket("/stream-transcribe")
async def stream_voice(
    websocket,
    language: str = "ru"
):
    """Stream voice transcription results"""
    try:
        await websocket.accept()
        
        async def receive_audio() -> AsyncGenerator[bytes, None]:
            while True:
                try:
                    data = await websocket.receive_bytes()
                    yield data
                except Exception:
                    break

        # Process streaming audio
        async for result in stream_transcription(receive_audio(), language):
            await websocket.send_json(result)

    except Exception as e:
        await websocket.close(code=1001, reason=str(e))

@router.post("/to-requirement",
    response_model=RequirementExtractionResponse,
    summary="Convert voice to structured requirement")
async def voice_to_requirement(
    file: UploadFile = File(...),
    request: VoiceTranscriptionRequest = Depends()
):
    """Convert voice input to structured requirement format"""
    try:
        # Read and transcribe audio
        audio_bytes = await file.read()
        raw_transcription = await transcribe_audio(
            audio_bytes,
            request.language
        )
        
        # Format transcription
        formatted_text = await format_transcription(
            raw_transcription,
            request.language
        )
        
        # Extract requirement components
        requirements = await extract_requirements(
            formatted_text,
            request.language
        )
        
        return RequirementExtractionResponse(
            components=requirements,
            confidence=0.8,  # You might want to calculate this
            raw_text=formatted_text
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Requirement extraction failed: {str(e)}"
        )
