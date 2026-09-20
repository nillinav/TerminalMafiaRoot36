import asyncio
import json
import random
import time
from ollama import AsyncClient

# Global context for the current game
game_history = []

def clear_context():
    """Clears the LLM context after every game."""
    game_history.clear()
    print("[BOT-AI] Context cleared.")

async def generate_bot_responses(bots_info: dict, phase: str, duration: int) -> list:
    """
    Calls Ollama asynchronously using the official package.
    Forces JSON schema and ruthlessly cuts off if it takes too long.
    """
    if not bots_info:
        return []

    # Prepare data for prompt
    bot_names = [b["name"] for b in bots_info.values()]
    recent_history = "\n".join(game_history[-5:]) # Cut corners: limit history length
    
    # FIX: Use an ENUM in the schema to strictly force the LLM 
    # to output the exact bot names, preventing mapping crashes.
    response_schema = {
        "type": "object",
        "properties": {
            "dialogues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "bot_name": {
                            "type": "string",
                            "enum": bot_names  # Forces LLM to pick exactly from active bots
                        },
                        "message": {"type": "string"}
                    },
                    "required": ["bot_name", "message"]
                }
            }
        },
        "required": ["dialogues"]
    }

    prompt = f"""
    You are the text engine for an AI Mafia game.
    Current Phase: {phase}
    Recent Game Events:
    {recent_history}
    
    Generate 0 to 3 short chat messages for EACH of these active bots: {', '.join(bot_names)}.
    React to the events. If it's night time, ghosts don't speak, just sleep.
    Keep the messages to one sentence.
    """

    responses = []
    # Cut corners: Give LLM a strict deadline so it never bleeds past the phase timer
    timeout_limit = max(1.0, duration - 3.0) 

    try:
        # Start generation using AsyncClient so the server doesn't freeze
        start_time = time.perf_counter()
        
        # We wrap it in asyncio.wait_for to force a crash/timeout if it's too slow
        response = await asyncio.wait_for(
            AsyncClient().generate(
                model='gemma4:e2b', 
                prompt=prompt,
                format=response_schema,
                options={
                    'temperature': 0.85,
                    'num_predict': 150 # Keep it short for speed
                },
                # FIX: Do not use keep_alive=0. Keeping the model in VRAM for 5 mins 
                # prevents massive loading lag on every single phase.
                keep_alive='5m' 
            ),
            timeout=timeout_limit
        )
        
        elapsed = time.perf_counter() - start_time
        print(f"[BOT-AI] Generated in {elapsed:.2f}s")
        
        # Parse the guaranteed JSON safely
        raw_resp = response.get('response', '{}')
        data = json.loads(raw_resp)
        dialogues = data.get("dialogues", [])
        
        # Map generated text to actual bot IDs and assign random send delays
        for dialog in dialogues:
            generated_name = dialog.get("bot_name", "")
            message = dialog.get("message", "")
            
            # Find which bot this belongs to
            for bid, binfo in bots_info.items():
                # Since we used an enum in the schema, we can safely do exact matching
                if binfo["name"] == generated_name:
                    # Randomize WHEN the bot speaks during the phase so it feels organic
                    delay = random.uniform(1.0, max(1.0, duration - 2.0))
                    responses.append({
                        "id": bid,
                        "text": message,
                        "delay": delay
                    })
                    break

    except asyncio.TimeoutError:
        print("[BOT-AI] LLM took too long! Bots will remain silent to keep game moving.")
    except json.JSONDecodeError:
        print("[BOT-AI] LLM returned invalid JSON structure.")
    except Exception as e:
        print(f"[BOT-AI] Unexpected Error: {str(e)}")
        
    return responses


def get_bot_action(bot_role: str, valid_targets: list):
    """
    Cut corner: Use standard logic for targets to prevent LLM hallucination crashes.
    Asking the LLM to format JSON for voting/killing logic is too slow and risky.
    """
    if not valid_targets:
        return None
    return random.choice(valid_targets)