import asyncio
import json
import random
import re
import time
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from ollama import AsyncClient

# 1. Reuse a single client instance to prevent connection overhead/leaks
_ollama_client = AsyncClient()

# Global context for the current game
game_history: List[str] = []

def clear_context():
    """Clears the LLM context after every game."""
    game_history.clear()
    print("[BOT-AI] Context cleared.")


# 2. Use Pydantic models for structured outputs (Ollama native format)
class DialogueItem(BaseModel):
    bot_name: str = Field(description="Name of the bot speaking")
    message: str = Field(description="A short, single-sentence chat response")

class DialogueResponse(BaseModel):
    dialogues: List[DialogueItem]


def extract_and_clean_json(text: str) -> str:
    """
    Cleans raw LLM response by stripping Markdown code fences 
    and slicing out the outermost JSON structure.
    """
    if not text:
        return "{}"
    
    text = text.strip()
    
    # Remove markdown ```json ... ``` fences if present
    markdown_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if markdown_match:
        text = markdown_match.group(1).strip()
        
    # Extract text strictly between the first '{' and last '}'
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        text = text[start_idx : end_idx + 1]
        
    return text


async def generate_bot_responses(bots_info: dict, phase: str, duration: int) -> list:
    """
    Calls Ollama asynchronously using structured outputs and safe parsing.
    """
    if not bots_info:
        return []

    # Safe extraction of bot names
    bot_names = [
        b["name"] for b in bots_info.values() 
        if isinstance(b, dict) and "name" in b
    ]
    if not bot_names:
        return []

    recent_history = "\n".join(game_history[-5:]) if game_history else "Game started."
    
    prompt = f"""
You are the text engine for an AI Mafia game.
Current Phase: {phase}
Recent Game Events:
{recent_history}

Generate 0 to 3 short chat messages total among these active bots: {', '.join(bot_names)}.
Rules:
- Choose from these bot names: {', '.join(bot_names)}.
- Keep each message to exactly one short sentence.
"""

    responses = []
    # Ensure realistic minimum timeout (at least 3.0 seconds)
    timeout_limit = max(3.0, float(duration - 1))

    try:
        start_time = time.perf_counter()
        
        # Pass Pydantic schema to Ollama's format parameter
        schema = DialogueResponse.model_json_schema()

        response = await asyncio.wait_for(
            _ollama_client.generate(
                model='gemma4:e2b',
                prompt=prompt,
                format=schema,
                options={
                    'temperature': 0.1,   # FIX: Low temperature ensures valid JSON syntax
                    'num_predict': 512     # FIX: Increased from 150 to avoid truncated JSON
                },
                keep_alive='5m'
            ),
            timeout=timeout_limit
        )
        
        elapsed = time.perf_counter() - start_time
        print(f"[BOT-AI] Generated in {elapsed:.2f}s")
        
        raw_resp = response.get('response', '')
        cleaned_json = extract_and_clean_json(raw_resp)
        
        # Safe JSON decoding
        data = json.loads(cleaned_json)
        
        # Extract dialogues list safely
        dialogues = data.get("dialogues", []) if isinstance(data, dict) else []

        # Case-insensitive mapping lookup for bot names
        name_to_id = {
            binfo["name"].strip().lower(): bid 
            for bid, binfo in bots_info.items() 
            if isinstance(binfo, dict) and "name" in binfo
        }

        for dialog in dialogues:
            if not isinstance(dialog, dict):
                continue

            generated_name = str(dialog.get("bot_name", "")).strip()
            message = str(dialog.get("message", "")).strip()

            if not message or not generated_name:
                continue

            gen_name_lower = generated_name.lower()
            matched_id = name_to_id.get(gen_name_lower)
            
            # Fallback matching if the LLM slightly altered the bot name
            if not matched_id:
                for b_name_lower, b_id in name_to_id.items():
                    if b_name_lower in gen_name_lower or gen_name_lower in b_name_lower:
                        matched_id = b_id
                        break

            if matched_id:
                # Calculate safe random delay
                max_delay = max(1.0, float(duration) - 1.0)
                delay = random.uniform(0.5, max_delay)

                responses.append({
                    "id": matched_id,
                    "text": message,
                    "delay": delay
                })

    except asyncio.TimeoutError:
        print("[BOT-AI] LLM generation timed out! Bots will remain silent.")
    except json.JSONDecodeError as e:
        print(f"[BOT-AI] Invalid JSON received from model: {e}")
    except Exception as e:
        print(f"[BOT-AI] Unexpected Error: {str(e)}")
        
    return responses


def get_bot_action(bot_role: str, valid_targets: list):
    """
    Standard target selection logic to prevent hallucination crashes.
    """
    if not valid_targets:
        return None
    return random.choice(valid_targets)