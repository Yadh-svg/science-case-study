"""
Batch Processor for Parallel Question Generation
Groups questions by type and processes them in parallel batches.
"""

import asyncio
from typing import List, Dict, Any, Optional
from collections import defaultdict
import logging

import os

from llm_engine import run_gemini_async
from prompt_builder import build_prompt_for_batch, get_files

# ... (imports)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 4


def _save_metadata_to_file(metadata: Dict[str, Any], batch_key: str) -> Optional[str]:
    """
    Save extracted metadata to a file in metadata_logs directory.
    """
    if not metadata:
        return None
        
    try:
        from pathlib import Path
        import time
        import json
        
        log_dir = Path("metadata_logs")
        log_dir.mkdir(exist_ok=True)
        
        # Clean batch key for filename
        clean_key = "".join(c if c.isalnum() or c in "._-" else "_" for c in batch_key)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"metadata_{clean_key}_{timestamp}.txt"
        filepath = log_dir / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            # Save as pretty JSON as shown in user example
            f.write(json.dumps(metadata, indent=2))
        
        logger.info(f"Metadata saved to {filepath}")
        return str(filepath)
    except Exception as e:
        logger.error(f"Failed to save metadata: {e}")
        return None


def extract_first_json_match(text: str) -> Dict[str, Any]:
    """
    Helper to find first valid JSON object using raw_decode.
    Handles trailing text (like '```') automatically.
    """
    import json
    try:
        # Find closest opening brace
        start_idx = text.find('{')
        if start_idx == -1:
            return None 
        
        # Use raw_decode which returns (obj, end_index) and ignores trailing text
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(text, idx=start_idx)
        return obj
    except Exception:
        return None



def extract_core_skill_metadata(response_text: str) -> Dict[str, Any]:
    """
    Extract the core skill JSON metadata from LLM response.
    
    Expected format: JSON object where values are comma-separated strings.
    Example: {"batch_summary": "concept1, concept2, concept3"}
    """
    # Use robust JSON extractor (no regex dependency)
    metadata = extract_first_json_match(response_text)
    
    if metadata:
        # Validate structure - one of the required keys must be present
        required_keys = ['batch_summary', 'core_equation', 'solution_pattern', 'scenario_signature', 'context_domain', 'answer_form']
        if any(key in metadata for key in required_keys):
             # Ensure values are strings (not lists) for consistency, though LLM should output strings
             clean_metadata = {}
             for k, v in metadata.items():
                 if isinstance(v, list):
                     clean_metadata[k] = ", ".join(str(x) for x in v)
                 else:
                     clean_metadata[k] = str(v)
             
             # Calculate total entries across all metadata keys
             total_entries = 0
             for v in clean_metadata.values():
                 if v and isinstance(v, str):
                     total_entries += len([item for item in v.split(',') if item.strip()])
             
             logger.info(f"Extracted cumulative metadata with approx {total_entries} total entries")
             return clean_metadata

    logger.warning("Could not extract core skill metadata from response")
    return {}



def group_questions_by_type_and_topic(questions_config: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group questions by question type for batch processing using Priority Packing.
    
    Strategy:
    1. Group by Type.
    2. Within each Type, grouping by Topic.
    3. For each Topic, extract FULL BATCHES (size 4) immediately.
    4. Collect all remaining questions (remainders) into a pool.
    5. Pack the remainder pool into mixed batches of size 4.
    
    This ensures maximal topic coherence in batches to avoid duplication issues 
    while maintaining efficient batch sizes.
    """
    grouped_by_type = defaultdict(list)
    BATCH_SIZE = DEFAULT_BATCH_SIZE

    # 1. Initial Grouping by Type
    for idx, q_config in enumerate(questions_config):
        q_type = q_config.get('type', 'MCQ')
        q_config['original_index'] = idx
        grouped_by_type[q_type].append(q_config)
    
    final_grouped = {}

    for q_type, type_questions in grouped_by_type.items():
        # Smart Preservation Logic
        # Goal: Preserve original order unless we detect INEFFICIENT topic splitting.
        
        # 1. Analyze Input Batches (Hypothetical)
        needs_optimization = False
        topic_batch_map = defaultdict(list)
        
        # Simulate batch assignment based on current order
        for i, q in enumerate(type_questions):
            current_batch_idx = i // BATCH_SIZE
            raw_topic = q.get('topic', '') or 'Unknown'
            # Enhanced normalization: lower, strip, and collapse internal spaces
            topic_key = " ".join(str(raw_topic).strip().lower().split())
            topic_batch_map[topic_key].append(current_batch_idx)

        # 2. Check for inefficiency
        for topic, batch_indices in topic_batch_map.items():
            # If topic appears in only one batch -> Efficient.
            unique_batches = sorted(list(set(batch_indices)))
            if len(unique_batches) <= 1:
                continue
            
            # If topic spans multiple batches, check usage.
            # It is EFFICIENT if all earlier batches are saturated with this topic?
            # Or simpler: It is INEFFICIENT if a topic is split across batches 
            # where the earlier batch had < BATCH_SIZE questions of that topic?
            # NO, earlier batch might be full of OTHER topics.
            
            # Definition: INEFFICIENT if we have multiple partial chunks of the same topic 
            # that COULD be combined into a fuller chunk.
            # Example Bad: Batch 1 has 2 'A', Batch 2 has 2 'A'. (Total 4 'A').
            # We could have put 4 'A' in one batch.
            
            # We check if the topic count in any batch is partial (< 4) AND there are more of that topic elsewhere.
            # Actually, "Priority Packing" puts 4s together.
            # So if we see a topic with total count >= 4, but it never forms a chunk of 4 in input -> INEFFICIENT.
            # Or if total count < 4, but it is split (e.g. 1 in B1, 1 in B2) -> INEFFICIENT.
            
            total_count = len(batch_indices)
            
            # Check consistency
            # Count occurrences per batch
            counts_per_batch = defaultdict(int)
            for b_idx in batch_indices:
                counts_per_batch[b_idx] += 1
                
            # If any batch has a partial amount (< BATCH_SIZE) AND we have other batches with this topic,
            # could we have done better?
            # Yes, we could have combined them.
            # Exception: If the split is necessary because we have too many (e.g. 6 items -> 4 + 2).
            # In that case, one batch MUST have 4.
            # So if we have NO batch with 4 items for this topic, but we have multiple batches -> Could be potentially optimized?
            # Wait, if total=6, and we have 3 in B1, 3 in B2 -> Inefficient (should be 4, 2).
            
            # Rule: Reorder if we find a topic that is split across batches AND doesn't have a max-capacity chunk (4) where possible.
            has_full_chunk = any(c == BATCH_SIZE for c in counts_per_batch.values())
            
            if total_count >= BATCH_SIZE and not has_full_chunk:
                needs_optimization = True
                logger.info(f"[{q_type}] Optimization needed: Topic '{topic}' (Count {total_count}) fragmented inefficiently across batches {dict(counts_per_batch)}")
                break
                
            # Also handle small fragmentation: 2 in B1, 2 in B2 (Total 4).
            # total_count=4. has_full_chunk=False. -> True. Correct.
            
            # What about Total=2? 1 in B1, 1 in B2.
            # total_count=2. < BATCH_SIZE.
            # Is 1+1 inefficient? Yes, we want 2 together.
            # So if total < BATCH_SIZE and len(unique_batches) > 1 -> Inefficient.
            if total_count < BATCH_SIZE and len(unique_batches) > 1:
                needs_optimization = True
                logger.info(f"[{q_type}] Optimization needed: Topic '{topic}' (Count {total_count}) fragmented across batches {unique_batches}")
                break

        if not needs_optimization:
            logger.info(f"  - {q_type}: {len(type_questions)} questions (Preserved User Order - Efficient)")
            final_grouped[q_type] = type_questions
            continue

        logger.info(f"  - {q_type}: Reordering for efficiency (Priority Packing applied)")
        
        # 3. Priority Packing (Original Logic)
        topic_map = defaultdict(list)
        topic_order = [] # Preserve original order of topics
        for q in type_questions:
            # Normalize topic: lowercase, strip, collapse spaces. Handle None.
            raw_topic = q.get('topic', '') or 'Unknown'
            topic_key = " ".join(str(raw_topic).strip().lower().split())
            if topic_key not in topic_map:
                topic_order.append(topic_key)
            topic_map[topic_key].append(q)
            
        final_list_for_type = []
        remainder_pool = []
        
        # 3. Extract Full Batches
        # Preserve original topic appearance order
        for topic in topic_order:
            questions = topic_map[topic]
            
            # While we have enough for a full batch
            while len(questions) >= BATCH_SIZE:
                # Take chunk
                chunk = questions[:BATCH_SIZE]
                questions = questions[BATCH_SIZE:] # Remove processed
                
                # Add to final list
                final_list_for_type.extend(chunk)
            
            # Add remaining to pool
            remainder_pool.extend(questions)
            
        # 4. Pack Remainder Pool
        # We sort the pool by original index to ensure that while topics are grouped when possible,
        # we don't unnecessarily reorder small topics or "leftovers" from one batch to much earlier ones.
        remainder_pool.sort(key=lambda x: x.get('original_index', 0))
        
        chunks = [remainder_pool[i:i + BATCH_SIZE] for i in range(0, len(remainder_pool), BATCH_SIZE)]
        for chunk in chunks:
            final_list_for_type.extend(chunk)
            
        final_grouped[q_type] = final_list_for_type
        
        logger.info(f"  - {q_type}: {len(final_list_for_type)} questions (Grouped by Topic & Preserving Order)")

    logger.info(f"Grouped {len(questions_config)} questions into {len(final_grouped)} types with Topic-Based Grouping.")
    
    return final_grouped



async def generate_raw_batch(
    batch_key: str,
    questions: List[Dict[str, Any]],
    general_config: Dict[str, Any],
    type_config: Dict[str, Any] = None,
    previous_batch_metadata: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Generate raw questions for a single batch (Stage 1).
    """
    logger.info(f"Generating RAW batch: {batch_key} ({len(questions)} questions)")
    
    try:
        # Build the prompt for this batch
        # Extract base type key (remove " - Batch X" suffix) for template lookup
        base_key = batch_key.split(' - Batch ')[0]
        prompt_data = build_prompt_for_batch(base_key, questions, general_config, type_config, previous_batch_metadata)
        
        prompt_text = prompt_data['prompt']



        files = prompt_data.get('files', [])
        file_metadata = prompt_data.get('file_metadata', {})
        api_key = general_config['api_key']
        
        # Call Gemini API for generation
        result = await run_gemini_async(
            prompt=prompt_text,
            api_key=api_key,
            files=files,
            thinking_level="medium",
            file_metadata=file_metadata,
            # Use a more explicit log name for regeneration if override is on
            log_name=f"Regeneration_{batch_key}" if general_config.get('save_prompts_override') else f"{batch_key}_Gen",
            save_prompt=False  # Disabled prompt saving
        )


        
        # Add metadata
        result['question_count'] = len(questions)
        result['used_file'] = len(files) > 0
        result['batch_key'] = batch_key
        result['file_source'] = file_metadata.get('source_type', 'N/A')
        
        return result
        
    except Exception as e:
        logger.error(f"Error generating raw batch {batch_key}: {e}")
        return {
            'error': str(e),
            'text': f"Error generating {batch_key} questions: {str(e)}",
            'elapsed': 0,
            'question_count': len(questions),
            'batch_key': batch_key
        }


async def validate_batch(
    batch_key: str,
    validation_prompt_text: str,
    general_config: Dict[str, Any],
    files: List = None,
    file_metadata: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Validate a batch of questions using Gemini 2.5 Pro (Stage 2).
    """
    logger.info(f"Validating batch: {batch_key}")
    
    try:
        api_key = general_config['api_key']
        

        
        # Call Gemini API for validation with files if available
        result = await run_gemini_async(
            prompt=validation_prompt_text,
            api_key=api_key,
            files=files,
            thinking_level="medium",
            file_metadata=file_metadata,
            log_name=f"{batch_key}_Val",
            # ONLY save validation prompts if explicitly requested AND it's NOT a regeneration run 
            # (unless they really want validation of regeneration too, but let's assume they don't for now)
            save_prompt=general_config.get('save_prompts_override', False) and not general_config.get('is_regeneration')
        )
        
        result['batch_key'] = batch_key
        return result
        
    except Exception as e:
        logger.error(f"Error validating batch {batch_key}: {e}")
        return {
            'error': str(e),
            'text': f"Error validating {batch_key} questions: {str(e)}",
            'elapsed': 0,
            'batch_key': batch_key
        }


async def process_batches_pipeline(
    questions_config: List[Dict[str, Any]],
    general_config: Dict[str, Any],
    progress_callback=None
) -> Dict[str, Dict[str, Any]]:
    """
    Process questions in a BATCHED SEQUENTIAL pipeline:
    1. Split questions into batches of 5 for each type.
    2. Process batches of the SAME type SEQUENTIALLY (Batch 1 -> Batch 2).
    3. Process different question types in PARALLEL.
    
    Architecture:
    ┌─ MCQ Task ───────────────────────────────────┐
    │  [Batch 1 Gen -> Val] → [Batch 2 Gen -> Val] │
    └──────────────────────────────────────────────┘
    ┌─ FIB Task ───────────────────────────────────┐
    │  [Batch 1 Gen -> Val] → [Batch 2 Gen -> Val] │
    └──────────────────────────────────────────────┘
    
    Returns:
        Flattened dictionary of results, e.g.:
        {
            "MCQ - Batch 1": {...},
            "MCQ - Batch 2": {...},
            "FIB - Batch 1": {...}
        }
    """
    logger.info(f"Starting batched pipeline processing for {len(questions_config)} questions")
    
    # Group questions by type
    grouped_questions = group_questions_by_type_and_topic(questions_config)
    
    # Load validation prompt template
    try:
        import yaml
        with open('validation.yaml', 'r', encoding='utf-8') as f:
            validation_config = yaml.safe_load(f)
            validation_prompt_template = validation_config.get('validation_prompt', '')
            if not validation_prompt_template:
                logger.warning("Validation prompt not found under key 'validation_prompt'. Falling back to raw file read.")
                with open('validation.yaml', 'r', encoding='utf-8') as f:
                    validation_prompt_template = f.read()

    except Exception as e:
        logger.error(f"Failed to load validation.yaml: {e}")
        return {'error': "Critical: validation.yaml not found"}

    pipeline_results = {}
    
def split_generated_content(text: str) -> Dict[str, str]:
    """
    Split the raw generated markdown into individual question blocks using the explicit delimiter.
    Delimiter: |||QUESTION_START|||
    """
    questions = {}
    
    # Check if delimiter exists
    if "|||QUESTION_START|||" not in text:
        logger.warning("Explicit delimiter '|||QUESTION_START|||' not found. Attempting fallback split by regex patterns.")
        
        # Fallback: Multi-pattern split
        # Matches:
        # 1. **Question [1]** or **Question 1**
        # 2. QUESTION 1 or Question 1:
        # 3. **Question 1:**
        import re
        # Pattern captures the index (Group 1)
        # We look for "Question" followed by optional space/bracket, digits, optional closing bracket/colon/bold chars
        # Examples: "**Question 1**", "Question [1]", "QUESTION 1"
        pattern = r'(?:\*\*|#|\n|^)?\s*(?:Question|QUESTION)\s*(?:\[)?(\d+)(?:\])?\s*(?:\*\*|:)?'
        
        # We use re.split capturing group 1 (the number)
        # Note: This might be too aggressive if "Question 1" appears in the text.
        # We try to anchor it or rely on markdown header syntax like ** or # if possible, but user said "QUESTION 1" is possible.
        # Let's try a robust pattern that requires newline before or is a clear header.
        
        # Revised Pattern:
        # (Newline or Start) + (Optional **) + Question/QUESTION + (Optional space) + [N] or N + (Optional ] or : or **)
        pattern = r'(?:\n|^)\s*(?:\*\*)?\s*(?:Question|QUESTION)\s*(?:\[)?\s*(\d+)\s*(?:\])?\s*(?:\*\*|:)?'
        
        parts = re.split(pattern, text)
        
        if len(parts) >= 2:
             questions = {}
             # parts[0] is preamble.
             # Loop: parts[1]=num, parts[2]=content, parts[3]=num...
             for i in range(1, len(parts), 2):
                q_num = parts[i]
                content = parts[i+1]
                # Reconstruct header for clarity (always use standard format for internal use)
                full_content = f"**Question [{q_num}]**\n{content}"
                key = f"question{q_num}"
                questions[key] = full_content.strip()
             
             logger.info(f"Fallback split found {len(questions)} items using regex.")
             return questions
        
        logger.warning("Fallback split also failed. returning full text.")
        return {"question1": text}
    
    # Split by delimiter
    # The first part might be preamble/plan
    parts = text.split("|||QUESTION_START|||")
    
    # Skip preamble (part 0)
    # But check if part 0 contains a question? Usually preamble is first.
    # If the output starts immediately with delimiter, part 0 is empty.
    
    q_index = 1
    start_index = 1
    
    # If the text starts with the delimiter, part 0 is empty string.
    if text.strip().startswith("|||QUESTION_START|||"):
        start_index = 1 # part 0 is empty
    elif len(parts) > 1:
        # Preamble exists
        start_index = 1
    else:
        # Should not happen based on 'if' check above
        start_index = 0

    for i in range(start_index, len(parts)):
        content = parts[i].strip()
        if not content: continue
        
        key = f"question{q_index}"
        questions[key] = content
        q_index += 1
        
    logger.info(f"Split generated content into {len(questions)} items: {list(questions.keys())}")
    return questions


async def process_single_batch_flow(
    batch_key: str,
    questions: List[Dict[str, Any]],
    general_config: Dict[str, Any],
    type_config: Dict[str, Any] = None,
    validation_prompt_template: str = "",
    validation_config: Dict[str, Any] = None,
    progress_callback=None,
    previous_batch_metadata: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Process a SINGLE batch through the full Generation -> Split -> Parallel Validation flow.
    
    Returns:
        Dict containing batch results and optionally 'core_skill_metadata' if extraction is enabled.
    """
    logger.info(f"[{batch_key}] Starting Parallel Flow")
    
    # --- STAGE 1: GENERATION ---
    raw_result = await generate_raw_batch(batch_key, questions, general_config, type_config, previous_batch_metadata)
    
    # Extract core skill metadata if enabled
    core_skill_metadata = {}
    if general_config.get('core_skill_enabled', False) and not raw_result.get('error'):
        core_skill_metadata = extract_core_skill_metadata(raw_result.get('text', ''))
        
        # Save metadata to file if extracted
        if core_skill_metadata:
            _save_metadata_to_file(core_skill_metadata, batch_key)
            
        # Count entries for logging
        entry_count = sum(len([item for item in str(v).split(',') if item.strip()]) for v in core_skill_metadata.values())
        logger.info(f"[{batch_key}] Extracted core skill metadata: {entry_count} entries")
    
    if raw_result.get('error'):
        logger.warning(f"[{batch_key}] Generation failed. Skipping validation.")
        result_payload = {
            'raw': raw_result,
            'validated': {'error': 'Skipped due to generation failure', 'text': ''},
            'core_skill_metadata': core_skill_metadata
        }
        if progress_callback: progress_callback(batch_key, result_payload)
        return {batch_key: result_payload, '_metadata': core_skill_metadata}

    # --- STAGE 2: BATCH VALIDATION (No Split) ---
    logger.info(f"[{batch_key}] Validating entire batch (all questions together)")
    
    # Prepare validation resources
    val_files = [] 
    val_file_metadata = {'source_type': 'None (Validation)', 'filenames': []}
    
    # Base Type Key for Structure Map lookup
    base_type_key = batch_key.split(' - Batch ')[0]
    structure_map = {
        "MCQ": "structure_MCQ",
        "Fill in the Blanks": "structure_FIB",
        "Case Study": "structure_Case_Study",
        "Multi-Part": "structure_Multi_Part",
        "Assertion-Reasoning": "structure_AR",
        "Descriptive": "structure_Descriptive",
        "Descriptive w/ Subquestions": "structure_Descriptive_w_subq"
    }
    structure_key = structure_map.get(base_type_key)
    
    # Load the actual structure format from validation_config
    structure_format = "Return a valid JSON object."  # Default fallback
    if validation_config and structure_key:
        structure_format = validation_config.get(structure_key, structure_format)
        logger.info(f"[{batch_key}] Using structure format: {structure_key}")
    else:
        logger.warning(f"[{batch_key}] No validation config or structure key found, using default")
    
    # Build context for the batch (all questions)
    context_lines = []
    for idx, q_config in enumerate(questions):
        topic_str = q_config.get('topic', 'Unknown')
        q_notes = q_config.get('additional_notes_text', '')
        spec = q_config.get('mcq_type') or q_config.get('fib_type') or q_config.get('descriptive_type') or "Standard"
        
        dok = q_config.get('dok', 'N/A')
        marks = q_config.get('marks', 'N/A')
        taxonomy = q_config.get('taxonomy', 'N/A')
        
        context_line = f"Question {idx+1}: Topic='{topic_str}', Type='{spec}', DOK='{dok}', Marks='{marks}', Taxonomy='{taxonomy}'"
        if q_notes:
            context_line += f", Notes='{q_notes}'"
        context_lines.append(context_line)
    
    batch_context = "\n".join(context_lines)
    
    # Construct validation prompt for entire batch
    val_prompt = validation_prompt_template.replace("{{GENERATED_CONTENT}}", raw_result['text'])
    val_prompt = val_prompt.replace("{{INPUT_CONTEXT}}", batch_context)
    val_prompt = val_prompt.replace("{{OUTPUT_FORMAT_RULES}}", structure_format)
    
    # Call validation API once for the entire batch
    validation_result = await validate_batch(batch_key, val_prompt, general_config, val_files, val_file_metadata)
    
    logger.info(f"[{batch_key}] Batch validation complete")
    
    # --- FALLBACK: Detect dropped questions and restore from raw generation ---
    import json as _json
    val_text = validation_result.get('text', '{}')
    
    # Split the raw generation into individual question blocks
    raw_split = split_generated_content(raw_result['text'])
    expected_count = len(raw_split)
    
    # Count how many questions the validator actually returned
    try:
        # Strip markdown fences if present
        clean_val = val_text.strip()
        if clean_val.startswith("```"):
            import re as _re
            clean_val = _re.sub(r"^```(?:json)?\s*\n?", "", clean_val, flags=_re.IGNORECASE)
            clean_val = _re.sub(r"\n?\s*```$", "", clean_val)
        val_obj = _json.loads(clean_val)
        validated_count = sum(1 for k in val_obj if isinstance(k, str) and k.lower().startswith('question'))
    except Exception:
        validated_count = 0
    
    if validated_count < expected_count:
        logger.warning(f"[{batch_key}] Validator returned {validated_count}/{expected_count} questions. Restoring missing questions from raw generation.")
        
        # Parse the existing validated output (or start fresh)
        try:
            merged = _json.loads(clean_val) if validated_count > 0 else {}
        except Exception:
            merged = {}
        
        # Fill in any missing questionN keys from raw split
        for q_key, q_content in raw_split.items():
            if q_key not in merged:
                merged[q_key] = q_content
                logger.info(f"[{batch_key}] Restored {q_key} from raw generation.")
        
        val_text = _json.dumps(merged, ensure_ascii=False)
    
    # The validation result should already contain properly formatted JSON
    final_validation_payload = {
        'text': val_text,
        'elapsed': validation_result.get('elapsed', 0),
        'batch_key': batch_key,
        'input_tokens': validation_result.get('input_tokens', 0),
        'output_tokens': validation_result.get('output_tokens', 0)
    }
    
    logger.info(f"[{batch_key}] Flow Complete")
    
    result_payload = {
        'raw': raw_result,
        'validated': final_validation_payload,
        'core_skill_metadata': core_skill_metadata
    }
    
    if progress_callback: progress_callback(batch_key, result_payload)
    return {batch_key: result_payload, '_metadata': core_skill_metadata}


async def process_batches_pipeline(
    questions_config: List[Dict[str, Any]],
    general_config: Dict[str, Any],
    progress_callback=None
) -> Dict[str, Dict[str, Any]]:
    """
    Process ALL batches. Uses PARALLEL flows by default, or SEQUENTIAL per-type
    when core_skill_enabled is True (to pass metadata between batches).
    """
    core_skill_enabled = general_config.get('core_skill_enabled', False)
    mode = "SEQUENTIAL (Core Skill)" if core_skill_enabled else "PARALLEL"
    logger.info(f"Starting {mode} pipeline for {len(questions_config)} questions")
    
    # Group questions by type
    grouped_questions = group_questions_by_type_and_topic(questions_config)
    
    # Load validation template
    try:
        import yaml
        with open('validation.yaml', 'r', encoding='utf-8') as f:
            validation_config = yaml.safe_load(f)
            validation_prompt_template = validation_config.get('validation_prompt', '')
    except Exception as e:
        logger.error(f"Failed to load validation.yaml: {e}")
        return {'error': "Critical: validation.yaml not found"}

    pipeline_results = {}
    
    if core_skill_enabled:
        # SEQUENTIAL PROCESSING: Process each type's batches sequentially to pass metadata
        logger.info("🔧 Core Skill enabled: Processing batches SEQUENTIALLY per type")
        
        for base_type_key, all_type_questions in grouped_questions.items():
            BATCH_SIZE = DEFAULT_BATCH_SIZE
            batches = [all_type_questions[i:i + BATCH_SIZE] for i in range(0, len(all_type_questions), BATCH_SIZE)]
            
            # Accumulated metadata for this type
            accumulated_metadata = {}
            
            for i, batch_questions in enumerate(batches):
                batch_key = f"{base_type_key} - Batch {i + 1}"
                
                # Count prior entries for logging
                prior_count = sum(len([item for item in str(v).split(',') if item.strip()]) for v in accumulated_metadata.values())
                logger.info(f"[Core Skill] Processing {batch_key} with {prior_count} prior metadata entries")
                
                # Process this batch with previous metadata
                result = await process_single_batch_flow(
                    batch_key=batch_key,
                    questions=batch_questions,
                    general_config=general_config,
                    type_config=None,
                    validation_prompt_template=validation_prompt_template,
                    validation_config=validation_config,
                    progress_callback=progress_callback,
                    previous_batch_metadata=accumulated_metadata if accumulated_metadata else None
                )
                
                # LOGIC UPDATE: We now accumulate metadata in Python, 
                # instead of expecting the LLM to pass back the full list.
                batch_metadata = result.pop('_metadata', {})
                if batch_metadata:
                    # Initialize if empty
                    if not accumulated_metadata:
                        accumulated_metadata = batch_metadata.copy()
                    else:
                        # Append new values to existing strings
                        for key, new_val in batch_metadata.items():
                            if key in accumulated_metadata:
                                # Append with comma
                                current_val = accumulated_metadata[key]
                                if new_val.strip():
                                    accumulated_metadata[key] = f"{current_val}, {new_val}"
                            else:
                                # New key, just add it
                                accumulated_metadata[key] = new_val
                    logger.info(f"[Core Skill] Updated cumulative metadata after {batch_key}")
                
                # Add batch results to pipeline results
                pipeline_results.update(result)
    else:
        # PARALLEL PROCESSING: Original behavior
        all_batch_tasks = []
        
        for base_type_key, all_type_questions in grouped_questions.items():
            BATCH_SIZE = DEFAULT_BATCH_SIZE
            batches = [all_type_questions[i:i + BATCH_SIZE] for i in range(0, len(all_type_questions), BATCH_SIZE)]
            
            for i, batch_questions in enumerate(batches):
                batch_key = f"{base_type_key} - Batch {i + 1}"
                
                # Create a task for this batch
                task = process_single_batch_flow(
                    batch_key=batch_key,
                    questions=batch_questions,
                    general_config=general_config,
                    type_config=None,
                    validation_prompt_template=validation_prompt_template,
                    validation_config=validation_config,
                    progress_callback=progress_callback,
                    previous_batch_metadata=None
                )
                all_batch_tasks.append(task)
                
        logger.info(f"🚀 Launching {len(all_batch_tasks)} batch flows in PARALLEL")
        
        # Run everything
        all_results_list = await asyncio.gather(*all_batch_tasks, return_exceptions=True)
        
        # Aggregate results
        for res in all_results_list:
            if isinstance(res, dict):
                # Remove internal _metadata key before adding to results
                res.pop('_metadata', None)
                pipeline_results.update(res)
            elif isinstance(res, Exception):
                logger.error(f"Batch flow failed: {res}")
            
    logger.info("Pipeline processing completed.")
    return pipeline_results


async def regenerate_specific_questions_pipeline(
    original_config: List[Dict[str, Any]],
    regeneration_map: Dict[str, List[int]],
    general_config: Dict[str, Any],
    progress_callback=None
) -> Dict[str, Dict[str, Any]]:
    """
    Regenerate SPECIFIC questions based on their original configuration.
    Wraps the standard batched pipeline for a subset of questions.
    """
    logger.info(f"Regenerating specific questions: {regeneration_map}")
    
    # 1. Sync indices using Priority Packing
    # This must match the original generation logic exactly
    grouped_batch_map = group_questions_by_type_and_topic(original_config)
    
    selected_configs_only = []
    
    # 2. Extract selected questions by batch_key and relative index
    for batch_key, indices in regeneration_map.items():
        # Handle new Batch Key format (e.g., "MCQ - Batch 1")
        base_type = batch_key.split(' - Batch ')[0]
        
        # Parse batch number from key if present
        import re
        batch_match = re.search(r'Batch (\d+)', batch_key)
        batch_num = int(batch_match.group(1)) if batch_match else 1
        
        if base_type not in grouped_batch_map:
            logger.warning(f"Type {base_type} not found in grouped map during regeneration")
            continue
            
        all_grouped_of_type = grouped_batch_map[base_type]
        
        # Calculate offset based on batch number
        # Default batch size is 4 
        BATCH_SIZE = DEFAULT_BATCH_SIZE
        offset = (batch_num - 1) * BATCH_SIZE
        
        for idx in indices:
            # idx is 1-based index WITHIN the batch (1..4)
            target_grouped_idx = offset + (idx - 1)
            
            if 0 <= target_grouped_idx < len(all_grouped_of_type):
                q_config = all_grouped_of_type[target_grouped_idx].copy()
                
                # Attach Context
                q_config['_is_being_regenerated'] = True
                
                # Original Text
                existing_content_map = general_config.get('existing_content_map', {})
                if batch_key in existing_content_map:
                    q_key = f"question{idx}"
                    original_text = existing_content_map[batch_key].get(q_key, "")
                    if original_text:
                        q_config['original_text'] = original_text
                
                # Regeneration Reason
                regeneration_reasons_map = general_config.get('regeneration_reasons_map', {})
                # Look up by "batch_key:idx"
                reason_id = f"{batch_key}:{idx}"
                reason = regeneration_reasons_map.get(reason_id, "")
                if reason:
                    q_config['regeneration_reason'] = reason
                
                # Override type to the specific batch key to preserve alignment in process_batches_pipeline
                # This ensures the parallel pipeline treats "MCQ - Batch 2" as a distinct task
                q_config['type'] = batch_key
                
                selected_configs_only.append(q_config)
            else:
                logger.warning(f"Index {idx} out of bounds for {batch_key} (Global mapping failed)")

    if not selected_configs_only:
        return {'error': "No valid questions were identified for regeneration. Check index mapping."}

    logger.info(f"Executing standard pipeline for {len(selected_configs_only)} selected questions...")
    
    # 3. Enable prompt saving for regeneration regardless of general config
    regeneration_config = general_config.copy()
    regeneration_config['save_prompts_override'] = False
    regeneration_config['is_regeneration'] = True
    
    # 4. Execute Standard Pipeline
    # Since we modified the 'type' to includes the batch number, the pipeline will 
    # process them in parallel batches corresponding to their original UI groups.
    results = await process_batches_pipeline(selected_configs_only, regeneration_config, progress_callback)
    
    # 5. Cleanup Keys
    # process_batches_pipeline adds " - Batch 1" because it thinks it's a new generation.
    # We strip the LAST " - Batch 1" to return keys exactly matching st.session_state.generated_output.
    fixed_results = {}
    for k, v in results.items():
        if ' - Batch 1' in k:
            original_key = k.rsplit(' - Batch 1', 1)[0]
            fixed_results[original_key] = v
        else:
            fixed_results[k] = v
            
    return fixed_results
