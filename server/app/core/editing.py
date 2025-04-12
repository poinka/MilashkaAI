# server/app/core/editing.py
import logging
from typing import Optional

# Import necessary components
from app.core.models import get_llm
import torch # For tensor operations if needed

# Constants
MAX_EDIT_TOKENS = 512 # Max tokens for the editing prompt + context
MAX_NEW_EDIT_TOKENS = 256 # Max tokens for the edited output

async def perform_text_edit(
    selected_text: str,
    prompt: str,
    language: str = "ru"
) -> str:
    """
    Edits the selected text based on the user's prompt using Gemma.
    """
    logging.info(f"Performing edit (language: {language}) on text: '{selected_text[:50]}...' with prompt: '{prompt[:50]}...'")
    model, tokenizer = get_llm()

    # Construct a clear prompt for the editing task
    # Include the original text and the instruction
    edit_prompt = f"""<start_of_turn>user
Edit the following text in {language} based on the instruction. Output only the modified text.

Instruction: "{prompt}"

Original Text: "{selected_text}"<end_of_turn>
<start_of_turn>model
Edited Text: """ # Prompt model to provide only the edited version

    try:
        inputs = tokenizer(edit_prompt, return_tensors="pt", truncation=True, max_length=MAX_EDIT_TOKENS - MAX_NEW_EDIT_TOKENS).to(model.device)

        outputs = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_EDIT_TOKENS,
            temperature=0.5, # Moderate temperature for creative but controlled editing
            top_p=0.9,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.eos_token_id
        )

        # Decode the generated part
        generated_ids = outputs[0, inputs.input_ids.shape[1]:]
        edited_text = tokenizer.decode(generated_ids, skip_special_tokens=True)

        # Basic cleanup (remove potential leading/trailing quotes or labels)
        edited_text = edited_text.strip().replace('"', '')
        # Remove potential prefix if the model repeats it
        if edited_text.lower().startswith("edited text:"):
            edited_text = edited_text[len("edited text:"):].strip()


        logging.info(f"Edited text result: '{edited_text[:100]}...'")
        return edited_text

    except Exception as e:
        logging.error(f"Error during text editing with Gemma: {e}", exc_info=True)
        # Return original text as fallback? Or raise error?
        logging.warning("Falling back to original text due to editing error.")
        return selected_text # Fallback to original text
