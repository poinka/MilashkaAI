import logging
from typing import Dict, Any, AsyncGenerator
import io
import numpy as np
import soundfile as sf
from fastapi import HTTPException, UploadFile
import asyncio
import torch
from app.core.models import get_asr_pipeline, get_llm
from app.core.config import settings
import librosa
import tempfile
import os
import subprocess

class AudioProcessor:
    def __init__(self):
        self.sample_rate = 16000
        self.supported_formats = settings.SUPPORTED_AUDIO_FORMATS
        self.max_duration = settings.MAX_AUDIO_DURATION

    async def validate_audio(self, file: UploadFile) -> None:
        # Check the MIME type first
        content_type = file.content_type.split(';')[0]  # Handle cases like "audio/webm;codecs=opus"
        if content_type not in [fmt.split(';')[0] for fmt in self.supported_formats]:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported audio format '{file.content_type}'. Supported formats: {', '.join(self.supported_formats)}"
            )

        # Read a small chunk to validate the audio file
        try:
            first_chunk = await file.read(8192)
            await file.seek(0)

            if len(first_chunk) == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Empty audio file"
                )

            # Try to open and validate the audio file
            with io.BytesIO(first_chunk) as buf:
                try:
                    with sf.SoundFile(buf) as f:
                        duration = len(f) / f.samplerate
                        if duration > self.max_duration:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Audio duration exceeds limit of {self.max_duration} seconds"
                            )
                except (sf.LibsndfileError, RuntimeError) as e:
                    # Special handling for WebM/Ogg formats which might not be readable by soundfile
                    if content_type in ['audio/webm', 'audio/ogg']:
                        # For these formats, we'll just check the file size as a rough estimate
                        # Assuming typical bitrate of 128kbps
                        file_size = len(first_chunk)
                        estimated_duration = (file_size * 8) / (128 * 1024)  # Convert bytes to seconds
                        if estimated_duration > self.max_duration:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Audio file too large. Maximum duration: {self.max_duration} seconds"
                            )
                    else:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid or corrupted audio file: {str(e)}"
                        )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error validating audio file: {str(e)}"
            )

    async def process_audio(self, file: UploadFile) -> np.ndarray:
        await self.validate_audio(file)
        
        audio_bytes = await file.read()
        
        # Create temporary files for conversion
        input_file = None
        output_file = None
        
        try:
            # Save incoming audio to a temp file
            with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
                tmp.write(audio_bytes)
                input_file = tmp.name
            
            # Create output temp file for WAV conversion
            output_file = input_file.replace('.webm', '.wav')
            
            # Convert to WAV using FFmpeg
            logging.info(f"Converting audio from {input_file} to {output_file}")
            try:
                # Try using ffmpeg-python if available
                try:
                    import ffmpeg
                    (
                        ffmpeg
                        .input(input_file)
                        .output(output_file, acodec='pcm_s16le', ac=1, ar=str(self.sample_rate))
                        .overwrite_output()
                        .run(quiet=True, capture_stdout=True, capture_stderr=True)
                    )
                    logging.info("Audio converted with ffmpeg-python")
                except (ImportError, ModuleNotFoundError):
                    # Fall back to subprocess if ffmpeg-python not available
                    logging.info("ffmpeg-python not available, falling back to subprocess")
                    subprocess.run([
                        'ffmpeg', '-i', input_file, 
                        '-acodec', 'pcm_s16le',
                        '-ac', '1',
                        '-ar', str(self.sample_rate),
                        '-y', output_file
                    ], check=True, capture_output=True)
                    logging.info("Audio converted with subprocess ffmpeg")
                    
                # Now load the converted WAV file with soundfile
                data, samplerate = sf.read(output_file)
                return data
                
            except Exception as ffmpeg_error:
                logging.error(f"FFmpeg conversion failed: {ffmpeg_error}")
                
                # If ffmpeg fails, try soundfile directly as fallback
                try:
                    # Reset file position
                    with io.BytesIO(audio_bytes) as buf:
                        data, samplerate = sf.read(buf)
                        if samplerate != self.sample_rate:
                            import resampy
                            data = resampy.resample(data, samplerate, self.sample_rate)
                        if len(data.shape) > 1:
                            data = data.mean(axis=1)  # Convert stereo to mono
                        return data
                except Exception as sf_error:
                    # If soundfile fails too, try librosa as final attempt
                    try:
                        logging.info(f"Attempting to load audio with librosa from {input_file}")
                        data, samplerate = librosa.load(
                            input_file, 
                            sr=self.sample_rate,
                            mono=True
                        )
                        return data
                    except Exception as librosa_error:
                        # All methods failed
                        logging.error(f"All audio processing methods failed. FFmpeg: {ffmpeg_error}, SoundFile: {sf_error}, Librosa: {librosa_error}")
                        raise HTTPException(
                            status_code=400, 
                            detail="Could not process audio. Please try a different recording format."
                        )
        finally:
            # Clean up temporary files
            for temp_file in [input_file, output_file]:
                if temp_file and os.path.exists(temp_file):
                    try:
                        os.unlink(temp_file)
                    except Exception as e:
                        logging.warning(f"Failed to delete temporary file {temp_file}: {e}")

async def transcribe_audio(audio_file: UploadFile, language: str) -> str:
    logging.info(f"Transcribing audio (language: {language})...")
    asr_pipeline = get_asr_pipeline()
    audio_processor = AudioProcessor()

    try:
        audio_data = await audio_processor.process_audio(audio_file)
        lang_map = {'ru': 'russian', 'en': 'english'}
        whisper_lang = lang_map.get(language.lower(), language)
        generate_kwargs = {"language": whisper_lang, "task": "transcribe"}

        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda":
            audio_data = torch.tensor(audio_data).cuda()

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
        raise HTTPException(status_code=408, detail="Transcription timed out")
    except Exception as e:
        logging.error(f"Error during transcription: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

async def stream_transcription(audio_stream: AsyncGenerator[bytes, None], language: str):
    buffer = io.BytesIO()
    audio_processor = AudioProcessor()

    async for chunk in audio_stream:
        buffer.write(chunk)
        
        if buffer.tell() >= settings.CHUNK_SIZE:
            buffer_data = buffer.getvalue()
            try:
                with io.BytesIO(buffer_data) as temp_file:
                    transcription = await transcribe_audio(UploadFile(file=temp_file, filename="chunk"), language)
                    yield {"text": transcription, "is_final": False}
            except Exception as e:
                logging.error(f"Error processing chunk: {e}")
                yield {"error": str(e), "is_final": False}
            
            buffer.seek(0)
            buffer.truncate()

    if buffer.tell() > 0:
        try:
            with io.BytesIO(buffer.getvalue()) as temp_file:
                transcription = await transcribe_audio(UploadFile(file=temp_file, filename="final"), language)
                yield {"text": transcription, "is_final": True}
        except Exception as e:
            logging.error(f"Error processing final chunk: {e}")
            yield {"error": str(e), "is_final": True}

async def format_transcription(raw_transcription: str, language: str) -> str:
    logging.info(f"Formatting transcription (language: {language})...")
    # Safety check for raw transcription
    if not raw_transcription or not isinstance(raw_transcription, str):
        logging.error(f"Invalid raw_transcription provided: {type(raw_transcription)}")
        return "" if not raw_transcription else str(raw_transcription)
    try:
        llm = get_llm()
        # Fallback: if LLMWrapper does not support formatting, just return the raw transcription
        if not hasattr(llm, 'format_text') or not callable(getattr(llm, 'format_text', None)):
            logging.warning("LLMWrapper does not support format_text; returning raw transcription.")
            return raw_transcription
        # If format_text exists, use it
        return llm.format_text(raw_transcription, language)
    except Exception as e:
        logging.error(f"Error during formatting: {e}")
        # TODO: Implement proper formatting using LLM when available
        return raw_transcription

async def extract_requirements(transcription: str, language: str) -> Dict[str, Any]:
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

        requirements = {
            "actor": "Not specified",
            "action": "Not specified",
            "object": "Not specified",
            "result": "Not specified"
        }

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
        for key, value in requirements.items():
            if value != "Not specified":
                requirements[key] = value[0].upper() + value[1:]

        logging.info(f"Extracted requirements: {requirements}")
        return requirements

    except asyncio.TimeoutError:
        logging.error("Requirements extraction timed out")
        return {k: "Extraction timed out" for k in ["actor", "action", "object", "result"]}
    except Exception as e:
        logging.error(f"Error extracting requirements: {e}")
        return {k: "Error during extraction" for k in ["actor", "action", "object", "result"]}