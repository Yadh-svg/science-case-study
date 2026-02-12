"""
LLM Engine for Gemini API Integration
Handles synchronous and asynchronous calls to Gemini API with File API support.
"""

import time
import asyncio
import logging
import tempfile
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


import threading

# Global lock for file reading to prevent race conditions during parallel batches
file_read_lock = threading.Lock()

def _save_prompt_to_file(prompt: str, log_name: str = "prompt") -> Optional[str]:
    """
    Save the final prompt to a file in prompt_logs directory.
    """
    try:
        log_dir = Path("prompt_logs")
        log_dir.mkdir(exist_ok=True)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{log_name}_{timestamp}.txt"
        filepath = log_dir / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(prompt)
        
        logger.info(f"Prompt saved to {filepath}")
        return str(filepath)
    except Exception as e:
        logger.error(f"Failed to save prompt: {e}")
        return None

def upload_files_to_gemini(files: List, api_key: str) -> List:
    """
    Upload multiple PDF and image files to Gemini File API and return file objects.
    
    Args:
        files: List of file-like objects (from Streamlit file_uploader)
        api_key: Gemini API key
        
    Returns:
        List of uploaded file objects from Gemini
    """
    if not files:
        return []
    
    client = genai.Client(api_key=api_key, http_options={'timeout': 600000})
    uploaded_files = []
    
    for file in files:
        tmp_path = None
        try:
            # Thread-safe file reading
            # We must lock because multiple parallel batches might try to seek/read 
            # the SAME shared file object (universal_pdf) simultaneously.
            with file_read_lock:
                # Reset file pointer to beginning
                file.seek(0)
                
                # Get file extension from filename
                filename = getattr(file, 'name', 'uploaded_file')
                file_ext = Path(filename).suffix if '.' in filename else '.pdf'
                
                # Create a temporary file (File API needs file path)
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
                    tmp_file.write(file.read())
                    tmp_path = tmp_file.name
            
            # Upload to Gemini File API (OUTSIDE the lock for parallelism)
            logger.info(f"Uploading file to Gemini File API: {filename}")
            
            uploaded = client.files.upload(file=tmp_path)
            uploaded_files.append(uploaded)
            
            logger.info(f"Successfully uploaded: {filename} (URI: {uploaded.name})")
            
        except Exception as e:
            logger.error(f"Failed to upload file {getattr(file, 'name', 'unknown')}: {e}")
            # Continue with other files even if one fails
            
        finally:
            # Clean up temp file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception as cleanup_error:
                   logger.warning(f"Failed to cleanup temp file {tmp_path}: {cleanup_error}")
    
    return uploaded_files


def run_gemini(
    prompt: str,
    api_key: str,
    files: Optional[List] = None,
    thinking_level: str = "medium",
    file_metadata: Optional[Dict[str, Any]] = None,
    log_name: str = "prompt",
    save_prompt: bool = True
) -> Dict[str, Any]:
    """
    Run Gemini model with optional PDF/image files using File API.
    
    Args:
        prompt: The text prompt to send
        api_key: Gemini API key
        files: List of file-like objects to upload (PDFs or images)
        thinking_level: Thinking level ("low", "medium", "high")
        file_metadata: Metadata about files (source_type, filenames)
        
    Returns:
        Dictionary with text, error, elapsed time, and token counts
    """
    out = {"text": "", "error": None, "elapsed": 0}
    start = time.time()
    
    try:
        # Save prompt to file if enabled
        if save_prompt:
            logger.info(f"Saving {log_name} prompt to file...")
            _save_prompt_to_file(prompt, log_name)

        # Initialize client with extended timeout (10 minutes) to accommodate thinking models
        # Initialize client with extended timeout (10 minutes = 600,000ms if units are ms, or long duration if seconds)
        # The API requires a deadline >= 10s for thinking models.
        client = genai.Client(api_key=api_key, http_options={'timeout': 600000})
        
        # Log execution start with file info
        if file_metadata and files:
            source_type = file_metadata.get('source_type', 'Unknown')
            filenames = file_metadata.get('filenames', [])
            logger.info(f"Starting Gemini | Files: {len(files)} files ({source_type}) | "
                       f"Files: {', '.join(filenames)} | Thinking level: {thinking_level}")
        else:
            logger.info(f"Starting Gemini | Files: None | Thinking level: {thinking_level}")
        
        # Build contents list
        contents = []
        
        # Upload files if provided
        if files:
            uploaded_files = upload_files_to_gemini(files, api_key)
            contents.extend(uploaded_files)
            
            if file_metadata:
                source_type = file_metadata.get('source_type', 'Unknown')
                filenames = file_metadata.get('filenames', [])
                logger.info(f"Added {len(uploaded_files)} file(s) to Gemini request | "
                           f"Source: {source_type} | Files: {', '.join(filenames)}")
        
        contents.append(prompt)
        
        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                include_thoughts=False,
                thinking_level=thinking_level
            )
        )
        
        # Using stream=True to be consistent with previous implementation
        stream = client.models.generate_content_stream(
            model="gemini-3-flash-preview",
            contents=contents,
            config=config
        )

        agg = ""
        chunk_count = 0
        usage_metadata = None
        
        for chunk in stream:
            txt = getattr(chunk, "text", "") or ""
            if txt:
                agg += txt
                chunk_count += 1
            
            # Capture usage metadata from the last chunk
            if hasattr(chunk, 'usage_metadata'):
                usage_metadata = chunk.usage_metadata

        out["text"] = agg
        
        # Extract token usage for cost calculation
        if usage_metadata:
            out["input_tokens"] = getattr(usage_metadata, 'prompt_token_count', 0)
            out["output_tokens"] = getattr(usage_metadata, 'candidates_token_count', 0)
            out["total_tokens"] = getattr(usage_metadata, 'total_token_count', 0)
            logger.info(f"Gemini completed | Chunks: {chunk_count} | Tokens: {out['total_tokens']} (in: {out['input_tokens']}, out: {out['output_tokens']}) | Time: {time.time() - start:.2f}s")
        else:
            out["input_tokens"] = 0
            out["output_tokens"] = 0
            out["total_tokens"] = 0
            logger.info(f"Gemini completed | Chunks: {chunk_count} | Output length: {len(agg)} chars | Time: {time.time() - start:.2f}s")
        
    except Exception as e:
        logger.error(f"Gemini execution failed: {e}")
        out["error"] = str(e)
        out["text"] = f"[Gemini Error] {e}"
        
    finally:
        out["elapsed"] = time.time() - start
        logger.debug(f"Gemini execution finished | Elapsed: {out['elapsed']:.2f}s")
    
    return out
async def run_gemini_async(
    prompt: str,
    api_key: str,
    files: Optional[List] = None,
    thinking_level: str = "medium",
    file_metadata: Optional[Dict[str, Any]] = None,
    log_name: str = "prompt",
    save_prompt: bool = True
) -> Dict[str, Any]:
    """
    Async wrapper for run_gemini.
    """
    return await asyncio.to_thread(run_gemini, prompt, api_key, files, thinking_level, file_metadata, log_name, save_prompt)
