from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from app.schemas.models import (
    VoiceTranscriptionResponse,
    VoiceToRequirementResponse,
    StructuredRequirement,
    StatusResponse
)
# Placeholder for actual voice processing logic
from app.core.voice import transcribe_audio, format_transcription, extract_requirements

router = APIRouter()

@router.post("/transcribe", response_model=VoiceTranscriptionResponse)
async def transcribe_voice_input(
    audio_file: UploadFile = File(...),
    language: str = Form("ru") # Default language 'ru'
):
    """
    Transcribes audio input using Whisper and optionally formats it using Gemma.
    """
    if not audio_file.content_type.startswith("audio/"):
         raise HTTPException(status_code=400, detail="Invalid file type. Please upload an audio file.")

    try:
        audio_bytes = await audio_file.read()

        # 1. Transcribe using Whisper
        raw_transcription = await transcribe_audio(audio_bytes, language)

        # 2. Format using Gemma (optional, based on requirements)
        # This assumes formatting is desired for general transcription endpoint
        formatted_transcription = await format_transcription(raw_transcription, language)

        return VoiceTranscriptionResponse(
            raw_transcription=raw_transcription,
            formatted_transcription=formatted_transcription
        )
    except Exception as e:
        print(f"Error during voice transcription: {e}")
        # Log the error properly
        raise HTTPException(status_code=500, detail=f"Failed to transcribe audio: {e}")
    finally:
        await audio_file.close()


@router.post("/to-requirement", response_model=VoiceToRequirementResponse)
async def voice_to_structured_requirement(
     audio_file: UploadFile = File(...),
     language: str = Form("ru") # Default language 'ru'
):
    """
    Transcribes audio and attempts to structure it into Actor-Action-Object-Result.
    """
    if not audio_file.content_type.startswith("audio/"):
         raise HTTPException(status_code=400, detail="Invalid file type. Please upload an audio file.")

    try:
        audio_bytes = await audio_file.read()

        # 1. Transcribe using Whisper
        transcription = await transcribe_audio(audio_bytes, language)

        # 2. Extract structured requirement using Gemma
        structured_req_dict = await extract_requirements(transcription, language)
        structured_requirement = StructuredRequirement(**structured_req_dict)

        return VoiceToRequirementResponse(
            structured_requirement=structured_requirement,
            original_transcription=transcription
        )
    except Exception as e:
        print(f"Error converting voice to requirement: {e}")
        # Log the error properly
        raise HTTPException(status_code=500, detail=f"Failed to process voice for requirement extraction: {e}")
    finally:
        await audio_file.close()