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
        save_prompt=False
    )
    
    if result.get('error'):
        return {"error": result['error']}
    
    # Parse JSON response — use strict=False to tolerate backslash sequences in markdown
    text = result.get('text', '')
    
    # Strip markdown code fences if present
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*\n?", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\n?\s*```$", "", clean)
        clean = clean.strip()
    
    decoder = json.JSONDecoder(strict=False)
    duplicates = None
    pos = 0
    
    # Scan for first JSON array or object
    while pos < len(clean):
        # Skip whitespace
        while pos < len(clean) and clean[pos].isspace():
            pos += 1
        if pos >= len(clean):
            break
        if clean[pos] in ('[', '{'):
            try:
                obj, _ = decoder.raw_decode(clean, pos)
                if isinstance(obj, list):
                    duplicates = obj
                    break
                elif isinstance(obj, dict):
                    # Could be {"duplicates": [...]} or {"variation1": "...", ...}
                    if "duplicates" in obj and isinstance(obj["duplicates"], list):
                        duplicates = obj["duplicates"]
                    else:
                        # Wrap dict as single-item list
                        duplicates = [obj]
                    break
            except json.JSONDecodeError:
                pos += 1
                continue
        else:
            pos += 1
    
    if duplicates is not None:
        return {"duplicates": duplicates, "elapsed": result.get('elapsed', 0)}
    
    return {"error": f"JSON parsing failed: Could not extract array from response", "raw_text": text[:500]}

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
