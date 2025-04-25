import logging
import sys
from io import StringIO
import contextlib
import os
from typing import Optional, List, Dict, Any
import uuid

from llama_cpp import Llama
from app.core.config import settings

logger = logging.getLogger('app.core.llm')

@contextlib.contextmanager
def capture_llm_logs():
    """Capture and filter llama.cpp initialization logs"""
    temp_stdout = StringIO()
    original_stdout = sys.stdout
    sys.stdout = temp_stdout
    try:
        yield temp_stdout
    finally:
        sys.stdout = original_stdout
        output = temp_stdout.getvalue()
        
        # Only log important messages
        for line in output.split('\n'):
            if any(key in line.lower() for key in ['error', 'warning', 'critical']):
                logger.warning(f"LLM: {line.strip()}")
            elif 'loaded successfully' in line.lower():
                logger.info(f"LLM: {line.strip()}")

class LLMWrapper:
    def __init__(self):
        self.model: Optional[Llama] = None
        self._load_model()
    
    def _load_model(self):
        """Load the LLM model with clean logging"""
        try:
            model_path = settings.LLM_MODEL_PATH
            model_name = os.path.basename(model_path)
            logger.info(f"Loading LLM model: {model_name}")
            
            with capture_llm_logs():
                self.model = Llama(
                    model_path=str(model_path),
                    n_ctx=4096,
                    n_batch=512,
                    verbose=False
                )
            
            logger.info(f"✓ LLM loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to load LLM: {str(e)}", exc_info=True)
            raise
    
    def create_chat_completion(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """Create a chat completion with detailed logging"""
        if not self.model:
            raise RuntimeError("LLM not initialized")
            
        try:
            request_id = kwargs.get('request_id', 'unknown')
            stream_mode = kwargs.get('stream', False)
            
            # Log input messages in a detailed format
            logger.info(f"[LLM-{request_id}] ===== INPUT START =====")
            logger.info(f"[LLM-{request_id}] Streaming mode: {stream_mode}")
            
            for msg in messages:
                role = msg['role'].upper()
                logger.info(f"[LLM-{request_id}] [{role}] ROLE")
                # Log content in chunks to avoid truncation
                content = msg['content']
                for i in range(0, len(content), 500):
                    logger.info(f"[LLM-{request_id}] {content[i:i+500]}")
            
            # Log important parameters
            param_log = []
            for key in ['temperature', 'top_p', 'max_tokens']:
                if key in kwargs:
                    param_log.append(f"{key}={kwargs[key]}")
            if param_log:
                logger.info(f"[LLM-{request_id}] Parameters: {', '.join(param_log)}")
            logger.info(f"[LLM-{request_id}] ===== INPUT END =====")
            
            # Get response - remove request_id from kwargs to prevent errors
            llm_kwargs = kwargs.copy()
            if 'request_id' in llm_kwargs:
                llm_kwargs.pop('request_id')
                
            response = self.model.create_chat_completion(messages=messages, **llm_kwargs)
            
            # For non-streaming responses, log complete output
            if not stream_mode and response and 'choices' in response and response['choices']:
                if 'message' in response['choices'][0]:
                    output = response['choices'][0]['message']['content']
                    logger.info(f"[LLM-{request_id}] ===== OUTPUT START =====")
                    for i in range(0, len(output), 500):
                        logger.info(f"[LLM-{request_id}] {output[i:i+500]}")
                    logger.info(f"[LLM-{request_id}] ===== OUTPUT END =====")
            
            return response
            
        except Exception as e:
            logger.error(f"Chat completion failed: {str(e)}", exc_info=True)
            raise
        
    def format_text(self, raw_transcription: str, language: str) -> str:
        """Format transcribed text using the LLM with a specific prompt. Only return the formatted text, not explanations."""
        if not self.model:
            raise RuntimeError("LLM not initialized")
        
        # Add unique request ID for tracking
        request_id = f"format-{str(uuid.uuid4())[:8]}"
        logger.info(f"[LLM-{request_id}] Starting transcription formatting")
        
        prompt = f"""<start_of_turn>user
Format the following transcribed text in {language}. Only output the improved text itself, without any explanations, comments, or bullet points. Do not add any extra text or formatting.

Text: \"{raw_transcription}\"<end_of_turn>
<start_of_turn>model
"""

        logger.info(f"[LLM-{request_id}] Sending prompt to LLM with raw text length: {len(raw_transcription)}")
        
        # Log the input prompt
        logger.info(f"[LLM-{request_id}] ===== FORMAT INPUT START =====")
        logger.info(f"[LLM-{request_id}] Language: {language}")
        logger.info(f"[LLM-{request_id}] Raw text: {raw_transcription}")
        logger.info(f"[LLM-{request_id}] ===== FORMAT INPUT END =====")
        
        response = self.model(prompt, max_tokens=256, temperature=0.3, stop=["<end_of_turn>"])
        
        # Log the raw response to debug any issues
        logger.info(f"[LLM-{request_id}] Raw response type: {type(response)}")
        logger.info(f"[LLM-{request_id}] Raw response: {response}")
        
        # Handle different response structures from llama-cpp
        formatted_text = ""
        if isinstance(response, dict):
            # Standard completion response structure
            if 'choices' in response and response['choices']:
                formatted_text = response['choices'][0].get('text', '')
            # Fall back to string representation if no text found
            if not formatted_text:
                formatted_text = str(response)
        elif isinstance(response, list) and response:
            # List response structure
            if 'generated_text' in response[0]:
                formatted_text = response[0]['generated_text']
            else:
                formatted_text = str(response[0])
        else:
            # Last resort fallback
            formatted_text = str(response)
        
        # Clean up the formatted text
        formatted_text = formatted_text.strip()
        
        # Log the extracted formatted text
        logger.info(f"[LLM-{request_id}] Extracted formatted text: {formatted_text}")
        
        # If the model still outputs explanations, try to cut at the first markdown or explanation marker
        for marker in ["**Explanation", "Explanation", "\n- ", "\n* ", "\n1.", "\n\n"]:
            idx = formatted_text.find(marker)
            if idx > 0:
                formatted_text = formatted_text[:idx].strip()
                logger.info(f"[LLM-{request_id}] Trimmed at marker '{marker}' to: {formatted_text}")
                
        # Remove any leading/trailing quotes
        if formatted_text.startswith('"') and formatted_text.endswith('"'):
            formatted_text = formatted_text[1:-1].strip()
            logger.info(f"[LLM-{request_id}] Removed surrounding quotes: {formatted_text}")
        
        logger.info(f"[LLM-{request_id}] Formatting completed. Final text: {formatted_text}")
        return formatted_text
# Global LLM instance
_llm_instance: Optional[LLMWrapper] = None

def get_llm() -> Optional[LLMWrapper]:
    """Get the global LLM instance"""
    global _llm_instance
    if not _llm_instance:
        _llm_instance = LLMWrapper()
    return _llm_instance
