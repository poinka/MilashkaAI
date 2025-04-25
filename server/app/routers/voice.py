from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
import asyncio
import logging
import io
from typing import AsyncGenerator

from app.core.config import settings
from app.schemas.models import (
    VoiceTranscriptionRequest,
    VoiceTranscriptionResponse,
    RequirementExtractionResponse,
    CompletionRequest,        # Added for text formatting
    CompletionResponse        # Added for text formatting
)
from app.schemas.errors import ErrorResponse
from app.core.voice import (
    transcribe_audio,
    format_transcription,
    extract_requirements,
    stream_transcription
)

router = APIRouter(
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse}
    }
)

# New endpoint to format text from voice transcription
@router.post("/format", 
    response_model=CompletionResponse,
    summary="Format transcribed text")
async def format_text(request: CompletionRequest):
    try:
        formatted_text = await format_transcription(
            request.text,
            request.language
        )
        
        return CompletionResponse(
            completion=formatted_text
        )
    except Exception as e:
        logging.exception(f"Text formatting failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Text formatting failed: {str(e)}"
        )

@router.post("/transcribe",
    response_model=VoiceTranscriptionResponse,
    summary="Transcribe audio file")
async def transcribe_voice(
    file: UploadFile = File(...),
    request: VoiceTranscriptionRequest = Depends()
):
    # First validate the content type to avoid processing invalid files
    if file.content_type not in settings.SUPPORTED_AUDIO_FORMATS:
        logging.error(f"Unsupported audio format: {file.content_type}")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format. Supported formats: {', '.join(settings.SUPPORTED_AUDIO_FORMATS)}"
        )
        
    try:
        # Read file content for size validation
        contents = await file.read()
        file_size = len(contents)
        
        # Reset file pointer after reading
        await file.seek(0)
        
        # Check file size
        if file_size > settings.MAX_AUDIO_SIZE:
            logging.error(f"Audio file too large: {file_size} bytes (max: {settings.MAX_AUDIO_SIZE})")
            raise HTTPException(
                status_code=400,
                detail=f"Audio file too large. Maximum size: {settings.MAX_AUDIO_SIZE / (1024*1024)}MB"
            )
            
        # Double check content type
        content_base_type = file.content_type.split(';')[0]  # Handle "audio/webm;codecs=opus"
        if content_base_type not in [fmt.split(';')[0] for fmt in settings.SUPPORTED_AUDIO_FORMATS]:
            logging.error(f"Content type validation failed: {file.content_type}")
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported audio format. Supported formats: {', '.join(settings.SUPPORTED_AUDIO_FORMATS)}"
            )
            
        logging.info(f"Processing audio file: {file.filename}, type: {file.content_type}, size: {file_size} bytes")
        
        # Используем оригинальный file, чтобы не терять content_type
        raw_transcription = await transcribe_audio(
            file,
            request.language
        )
        
        logging.info(f"Transcription completed successfully, length: {len(raw_transcription)}")
        
        # Format transcription
        formatted_text = await format_transcription(
            raw_transcription,
            request.language
        )
        
        # Return properly formatted response
        return VoiceTranscriptionResponse(
            text=formatted_text,
            is_final=True
        )

    except HTTPException as http_ex:
        # Re-raise HTTP exceptions as is
        raise
    except Exception as e:
        # Add more detailed logging of the exception
        logging.exception(f"Transcription failed with error: {str(e)}")
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
        # Reset file pointer to beginning
        await file.seek(0)
        
        # Pass the UploadFile object directly to transcribe_audio
        raw_transcription = await transcribe_audio(
            file,
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
