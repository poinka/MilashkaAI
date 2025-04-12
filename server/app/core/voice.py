# server/app/core/voice.py
import logging
from typing import Dict, Any, AsyncGenerator
from pathlib import Path
import io
import numpy as np
import soundfile as sf
from fastapi import HTTPException, UploadFile
import asyncio
import torch

from app.core.models import get_asr_pipeline, get_llm
from app.core.config import settings

class AudioProcessor:
    def __init__(self):
        self.sample_rate = 16000  # Standard for Whisper
        self.supported_formats = settings.SUPPORTED_AUDIO_FORMATS
        self.max_duration = settings.MAX_AUDIO_DURATION

    async def validate_audio(self, file: UploadFile) -> None:
        if file.content_type not in self.supported_formats:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported audio format. Supported: {', '.join(self.supported_formats)}"
            )

        # Read first chunk to validate format
        first_chunk = await file.read(8192)
        await file.seek(0)  # Reset position

        try:
            with io.BytesIO(first_chunk) as buf:
                with sf.SoundFile(buf) as f:
                    duration = len(f) / f.samplerate
                    if duration > self.max_duration:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Audio duration exceeds limit of {self.max_duration} seconds"
                        )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid audio file: {str(e)}"
            )

    async def process_audio(self, file: UploadFile) -> np.ndarray:
        await self.validate_audio(file)
        
        # Read and convert audio to the correct format for Whisper
        audio_bytes = await file.read()
        try:
            with io.BytesIO(audio_bytes) as buf:
                data, samplerate = sf.read(buf)
                if samplerate != self.sample_rate:
                    # Resample if necessary
                    import resampy
                    data = resampy.resample(data, samplerate, self.sample_rate)
                if len(data.shape) > 1:
                    data = data.mean(axis=1)  # Convert stereo to mono
                return data
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error processing audio: {str(e)}"
            )

async def transcribe_audio(audio_bytes: bytes, language: str) -> str:
    """
    Transcribes audio bytes using the loaded Whisper model.
    """
    logging.info(f"Transcribing audio (language: {language})...")
    asr_pipeline = get_asr_pipeline()
    audio_processor = AudioProcessor()

    try:
        # Process audio file
        audio_data = await audio_processor.process_audio(audio_bytes)

        # Map language codes
        lang_map = {'ru': 'russian', 'en': 'english'}
        whisper_lang = lang_map.get(language.lower(), language)
        generate_kwargs = {"language": whisper_lang, "task": "transcribe"}

        # Set up device and data type
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda":
            audio_data = torch.tensor(audio_data).cuda()

        # Transcribe with timeout
        async def transcribe_with_timeout():
            return await asyncio.wait_for(
                asyncio.to_thread(
                    asr_pipeline,
                    audio_data,
                    generate_kwargs=generate_kwargs,
                    batch_size=settings.BATCH_SIZE
                ),
                timeout=settings.MODEL_TIMEOUT
            )

        result = await transcribe_with_timeout()
        transcription = result["text"].strip()

        logging.info(f"Transcription result: '{transcription[:100]}...'")
        return transcription

    except asyncio.TimeoutError:
        logging.error("Transcription timed out")
        raise HTTPException(
            status_code=408,
            detail="Transcription timed out"
        )
    except Exception as e:
        logging.error(f"Error during transcription: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Transcription failed: {str(e)}"
        )

async def stream_transcription(audio_stream: AsyncGenerator[bytes, None], language: str):
    """
    Streams transcription results as they become available.
    """
    buffer = io.BytesIO()
    audio_processor = AudioProcessor()
    chunk_duration = 0

    async for chunk in audio_stream:
        buffer.write(chunk)
        
        # Process complete chunks
        if buffer.tell() >= settings.CHUNK_SIZE:
            buffer_data = buffer.getvalue()
            try:
                # Process chunk
                transcription = await transcribe_audio(buffer_data, language)
                yield {"text": transcription, "is_final": False}
            except Exception as e:
                logging.error(f"Error processing chunk: {e}")
                yield {"error": str(e), "is_final": False}
            
            # Reset buffer
            buffer.seek(0)
            buffer.truncate()

    # Process any remaining audio
    if buffer.tell() > 0:
        try:
            transcription = await transcribe_audio(buffer.getvalue(), language)
            yield {"text": transcription, "is_final": True}
        except Exception as e:
            logging.error(f"Error processing final chunk: {e}")
            yield {"error": str(e), "is_final": True}

async def format_transcription(raw_transcription: str, language: str) -> str:
    """
    Formats the raw transcription using Gemma with improved error handling.
    """
    logging.info(f"Formatting transcription (language: {language})...")
    model, tokenizer = get_llm()

    try:
        # Construct prompt with clear formatting instructions
        prompt = f"""<start_of_turn>user
Format the following transcribed text in {language}. Apply these improvements:
1. Fix punctuation and capitalization
2. Remove filler words and hesitations
3. Improve sentence structure while preserving meaning
4. Fix any obvious transcription errors

Text: "{raw_transcription}"<end_of_turn>
<start_of_turn>model
Formatted Text: """

        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=settings.MAX_INPUT_LENGTH
        ).to(model.device)

        # Generate with timeout
        async def generate_with_timeout():
            return await asyncio.wait_for(
                asyncio.to_thread(
                    model.generate,
                    **inputs,
                    max_new_tokens=settings.MAX_NEW_TOKENS,
                    temperature=0.3,
                    do_sample=False,  # Deterministic for formatting
                    eos_token_id=tokenizer.eos_token_id,
                    pad_token_id=tokenizer.eos_token_id
                ),
                timeout=settings.MODEL_TIMEOUT
            )

        outputs = await generate_with_timeout()
        generated_ids = outputs[0, inputs.input_ids.shape[1]:]
        formatted_text = tokenizer.decode(generated_ids, skip_special_tokens=True)

        # Clean up the formatted text
        formatted_text = formatted_text.strip().replace('"', '')
        if formatted_text.lower().startswith("formatted text:"):
            formatted_text = formatted_text[len("formatted text:"):].strip()

        logging.info(f"Formatted text: '{formatted_text[:100]}...'")
        return formatted_text

    except asyncio.TimeoutError:
        logging.error("Formatting timed out")
        return raw_transcription  # Fallback to raw text
    except Exception as e:
        logging.error(f"Error during formatting: {e}", exc_info=True)
        return raw_transcription  # Fallback to raw text

async def extract_requirements(transcription: str, language: str) -> Dict[str, Any]:
    """
    Extracts structured requirements with improved validation and error handling.
    """
    logging.info(f"Extracting requirements (language: {language})...")
    model, tokenizer = get_llm()

    try:
        prompt = f"""<start_of_turn>user
Extract structured requirement components from this text in {language}. Break it down into:

1. Actor: Who performs the action? (user role/system)
2. Action: What specific action is taken?
3. Object: What is the action performed on?
4. Result: What is the expected outcome?

Use these rules:
- Keep components concise but clear
- Use present tense
- Start each component with a capital letter
- If a component is not mentioned, write "Not specified"

Text: "{transcription}"<end_of_turn>
<start_of_turn>model
Actor: """

        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=settings.MAX_INPUT_LENGTH
        ).to(model.device)

        async def generate_with_timeout():
            return await asyncio.wait_for(
                asyncio.to_thread(
                    model.generate,
                    **inputs,
                    max_new_tokens=settings.MAX_NEW_TOKENS,
                    temperature=0.2,
                    do_sample=False,
                    eos_token_id=tokenizer.eos_token_id,
                    pad_token_id=tokenizer.eos_token_id
                ),
                timeout=settings.MODEL_TIMEOUT
            )

        outputs = await generate_with_timeout()
        generated_ids = outputs[0, inputs.input_ids.shape[1]:]
        structured_output = tokenizer.decode(generated_ids, skip_special_tokens=True)

        # Parse and validate the structured output
        requirements = {
            "actor": "Not specified",
            "action": "Not specified",
            "object": "Not specified",
            "result": "Not specified"
        }

        # Parse line by line with validation
        current_field = None
        for line in structured_output.split('\n'):
            line = line.strip()
            if not line:
                continue

            if ':' in line:
                field, value = line.split(':', 1)
                field = field.strip().lower()
                value = value.strip()

                if field in requirements and value and value.lower() not in ['none', 'not specified', 'blank', '']:
                    requirements[field] = value

        # Validate structure
        for key, value in requirements.items():
            if value != "Not specified":
                # Ensure proper capitalization
                requirements[key] = value[0].upper() + value[1:]

        logging.info(f"Extracted requirements: {requirements}")
        return requirements

    except asyncio.TimeoutError:
        logging.error("Requirements extraction timed out")
        return {k: "Extraction timed out" for k in ["actor", "action", "object", "result"]}
    except Exception as e:
        logging.error(f"Error extracting requirements: {e}", exc_info=True)
        return {k: "Error during extraction" for k in ["actor", "action", "object", "result"]}
