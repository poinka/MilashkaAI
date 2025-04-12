# server/app/core/voice.py
import logging
from typing import Dict, Any

# Import necessary components
from app.core.models import get_asr_pipeline, get_llm
import torch # For tensor operations if needed

# Constants
MAX_FORMAT_TOKENS = 256 # Max tokens for Gemma formatting task
MAX_REQUIREMENT_TOKENS = 512 # Max tokens for requirement extraction

async def transcribe_audio(audio_bytes: bytes, language: str) -> str:
    """
    Transcribes audio bytes using the loaded Whisper model.
    """
    logging.info(f"Transcribing audio (language: {language})...")
    asr_pipeline = get_asr_pipeline()

    try:
        # The pipeline expects audio input, often as a file path or numpy array.
        # We have bytes, so we might need to adapt or use a library like soundfile/librosa
        # if the pipeline doesn't handle bytes directly.
        # Let's assume the pipeline can handle bytes for now, but this might need adjustment.

        # Check if language needs mapping (Whisper uses language codes/names)
        # The pipeline might handle this automatically or require specific codes.
        # Forcing decode in multilingual models:
        generate_kwargs = {}
        if language:
             # Map common codes if needed, e.g., 'ru' -> 'russian'
             lang_map = {'ru': 'russian', 'en': 'english'}
             whisper_lang = lang_map.get(language.lower())
             if whisper_lang:
                 generate_kwargs = {"language": whisper_lang, "task": "transcribe"}
                 logging.info(f"Setting Whisper language to: {whisper_lang}")


        # Perform transcription
        # The input format might need adjustment (e.g., {"raw": audio_bytes, "sampling_rate": 16000})
        # Check the specific pipeline's documentation. Assuming it takes bytes directly:
        result = asr_pipeline(audio_bytes, generate_kwargs=generate_kwargs)

        transcription = result["text"]
        logging.info(f"Transcription result: '{transcription[:100]}...'")
        return transcription.strip()

    except Exception as e:
        logging.error(f"Error during Whisper transcription: {e}", exc_info=True)
        raise RuntimeError(f"Failed to transcribe audio: {e}") from e


async def format_transcription(raw_transcription: str, language: str) -> str:
    """
    Formats the raw transcription using Gemma (e.g., punctuation, capitalization).
    """
    logging.info(f"Formatting transcription (language: {language})...")
    model, tokenizer = get_llm()

    prompt = f"""<start_of_turn>user
Correct the punctuation, capitalization, and formatting of the following text in {language}. Make it read naturally. Do not change the meaning.

Text: "{raw_transcription}"<end_of_turn>
<start_of_turn>model
Formatted Text: """

    try:
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=MAX_REQUIREMENT_TOKENS - MAX_FORMAT_TOKENS).to(model.device)

        outputs = model.generate(
            **inputs,
            max_new_tokens=MAX_FORMAT_TOKENS,
            temperature=0.3, # Lower temperature for more deterministic formatting
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.eos_token_id # Set pad_token_id
        )

        # Decode, skipping prompt and special tokens
        generated_ids = outputs[0, inputs.input_ids.shape[1]:]
        formatted_text = tokenizer.decode(generated_ids, skip_special_tokens=True)

        # Basic cleanup
        formatted_text = formatted_text.strip().replace('"', '') # Remove potential leading/trailing quotes

        logging.info(f"Formatted transcription: '{formatted_text[:100]}...'")
        return formatted_text

    except Exception as e:
        logging.error(f"Error formatting transcription with Gemma: {e}", exc_info=True)
        # Return raw transcription as fallback? Or raise error?
        # For now, return raw as a fallback
        logging.warning("Falling back to raw transcription due to formatting error.")
        return raw_transcription


async def extract_requirements(transcription: str, language: str) -> Dict[str, Any]:
    """
    Uses Gemma to extract structured requirements (Actor, Action, Object, Result)
    from a transcribed text based on a template.
    """
    logging.info(f"Extracting structured requirements from transcription (language: {language})...")
    model, tokenizer = get_llm()

    # Define the desired structure clearly in the prompt
    prompt = f"""<start_of_turn>user
Analyze the following text in {language} and extract the requirement components based on this template:
- Actor: (The user role performing the action)
- Action: (The action being performed)
- Object: (The entity the action is performed on)
- Result: (The expected outcome)

If a component is not mentioned, leave it blank. Output only the structured components.

Text: "{transcription}"<end_of_turn>
<start_of_turn>model
Actor: """ # Prompt the model to start filling the template

    try:
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=MAX_REQUIREMENT_TOKENS - 100).to(model.device) # Reserve tokens for output

        outputs = model.generate(
            **inputs,
            max_new_tokens=100, # Max tokens for the structured output
            temperature=0.2, # Low temperature for structured extraction
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.eos_token_id
        )

        # Decode the generated part
        generated_ids = outputs[0, inputs.input_ids.shape[1]:]
        structured_output_raw = tokenizer.decode(generated_ids, skip_special_tokens=True)
        logging.debug(f"Raw structured output from Gemma: {structured_output_raw}")

        # Parse the generated string to extract components
        # This parsing needs to be robust to variations in Gemma's output format
        requirements = {
            "actor": None,
            "action": None,
            "object": None,
            "result": None
        }
        # Prepend "Actor: " to match the expected start
        full_output = "Actor: " + structured_output_raw
        lines = [line.strip() for line in full_output.split('\n') if ':' in line]
        for line in lines:
            try:
                key, value = line.split(':', 1)
                key_lower = key.strip().lower()
                value_strip = value.strip()
                if value_strip and value_strip.lower() != 'none' and value_strip.lower() != 'blank':
                    if key_lower == "actor":
                        requirements["actor"] = value_strip
                    elif key_lower == "action":
                        requirements["action"] = value_strip
                    elif key_lower == "object":
                        requirements["object"] = value_strip
                    elif key_lower == "result":
                        requirements["result"] = value_strip
            except ValueError:
                logging.warning(f"Could not parse line in structured output: '{line}'")
                continue # Skip malformed lines

        logging.info(f"Extracted requirements: {requirements}")
        return requirements

    except Exception as e:
        logging.error(f"Error extracting requirements with Gemma: {e}", exc_info=True)
        # Return empty structure on failure
        return {
            "actor": None,
            "action": None,
            "object": None,
            "result": None
        }
