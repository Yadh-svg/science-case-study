import asyncio
import yaml
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from llm_engine import run_gemini_async

logger = logging.getLogger(__name__)

async def duplicate_single_question_async(
    original_markdown: str,
    variation_count: int,
    custom_notes: str,
    context_file: Optional[Any],
    api_key: str
) -> Dict[str, Any]:
    """
    Duplicate a single question using Gemini.
    """
    # Load template
    prompts_path = Path(__file__).parent / "prompts.yaml"
    with open(prompts_path, 'r', encoding='utf-8') as f:
        prompts = yaml.safe_load(f)
    
    template = prompts.get('duplicate_question', '')
    if not template:
        return {"error": "Template duplicate_question not found in prompts.yaml"}
    
    # Simple string replacement
    file_context_str = "[File attached for context]" if context_file else "[No file provided]"
    
    prompt = template.replace("{{ORIGINAL_QUESTION}}", original_markdown)
    prompt = prompt.replace("{{CUSTOM_NOTES}}", custom_notes or "None")
    prompt = prompt.replace("{{FILE_CONTEXT}}", file_context_str)
    prompt = prompt.replace("{{VARIATION_COUNT}}", str(variation_count))
    
    # Call Gemini
    # Metadata for logging
    file_metadata = {
        "source_type": "duplication",
        "filenames": [getattr(context_file, 'name', 'uploaded_file')] if context_file else []
    }
    
    result = await run_gemini_async(
        prompt=prompt,
        api_key=api_key,
        files=[context_file] if context_file else None,
        thinking_level="medium",
        file_metadata=file_metadata,
        log_name="Duplication",
        save_prompt=True
    )
    
    if result.get('error'):
        return {"error": result['error']}
    
    # Parse JSON response
    text = result.get('text', '')
    try:
        # Robustly extract JSON array
        json_match = re.search(r'\[\s*\{.*?\}\s*\]', text, re.DOTALL)
        if json_match:
            duplicates = json.loads(json_match.group(0))
            return {"duplicates": duplicates, "elapsed": result.get('elapsed', 0)}
        else:
            # Try parsing whole text as JSON if no match found
            try:
                duplicates = json.loads(text)
                if isinstance(duplicates, list):
                    return {"duplicates": duplicates, "elapsed": result.get('elapsed', 0)}
            except:
                pass
            return {"error": "Could not extract JSON array from Gemini response", "raw_text": text[:500]}
    except Exception as e:
        return {"error": f"JSON parsing failed: {str(e)}", "raw_text": text[:500]}

async def process_parallel_duplication(
    requests: List[Dict[str, Any]],
    api_key: str
) -> List[Dict[str, Any]]:
    """
    Process multiple duplication requests in parallel.
    requests: list of { original_markdown, variation_count, custom_notes, context_file }
    """
    tasks = []
    for req in requests:
        tasks.append(duplicate_single_question_async(
            original_markdown=req['original_markdown'],
            variation_count=req['variation_count'],
            custom_notes=req.get('custom_notes', ''),
            context_file=req.get('context_file'),
            api_key=api_key
        ))
    
    return await asyncio.gather(*tasks)
