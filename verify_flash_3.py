import os
import asyncio
from llm_engine import run_gemini_async

async def verify():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY environment variable not set.")
        # Try to find it in find_key.py as per file list
        try:
            from find_key import get_api_key
            api_key = get_api_key()
        except:
            print("Failed to get API key from find_key.py")
            return

    print(f"Verifying with API key: {api_key[:5]}...{api_key[-5:] if len(api_key) > 10 else ''}")
    
    prompt = "Reply with exactly 'OK' if you are gemini-3-flash-preview."
    print(f"Sending prompt: {prompt}")
    
    result = await run_gemini_async(
        prompt=prompt,
        api_key=api_key,
        thinking_budget=0 # Flash 3 might not support high thinking budget or it might be different, let's test with 0 first
    )
    
    if result.get('error'):
        print(f"Error: {result['error']}")
    else:
        print(f"Response: {result['text']}")
        print(f"Tokens: {result.get('total_tokens')}")

if __name__ == "__main__":
    asyncio.run(verify())
