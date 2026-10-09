"""
Shared AI model connection for the POC.
Every script that needs the AI imports ask() from here, so the model
name and the key handling live in one place.

The key is read from a file named .env in this folder:
    GEMINI_API_KEY=your-key-here
Get a free key at https://aistudio.google.com/apikey

Note: on the free tier Google may use what we send to improve its
products. That is fine for the AdventureWorks sample database, but
real company table names need approval before being sent.
"""
import os
import time

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

# Tried in order, best first. The free tier allows only about 20 requests
# per day on each model, and sometimes answers "busy, try later", so we
# fall back to the next one. The "lite" models are weaker but still free.
MODEL_NAMES = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]
ATTEMPTS = 4
WAIT_SECONDS = 10
TIMEOUT_SECONDS = 90  # give up on a single reply after this long
# 429 = we hit the free tier's speed limit; 500/503 = Google's side is busy;
# 504 = Google did not answer within our time limit.
BUSY_CODES = {429, 500, 503, 504}

# Which model gave the most recent answer, so results can be traced.
last_model = None
# Models whose daily free allowance is used up. No point asking them again.
used_up = set()

load_dotenv()


def ask(prompt, answer_format):
    """
    Send a prompt to the AI and get the answer back in a fixed shape.

    answer_format is a pydantic class describing the fields we expect.
    The AI is forced to reply in that shape, so we never have to pick
    an answer out of free-flowing text.
    """
    global last_model
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError(
            "No Gemini key found. Create a file named .env in this folder "
            "containing the line:  GEMINI_API_KEY=your-key-here"
        )
    # Without a time limit, one lost reply would hang the program forever.
    # The library must not silently repeat a request, because every repeat
    # counts against the small daily allowance. We do our own retrying below.
    client = genai.Client(http_options=types.HttpOptions(
        timeout=TIMEOUT_SECONDS * 1000,
        retry_options=types.HttpRetryOptions(attempts=1),
    ))
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=answer_format,
        # We never let the AI call our code by itself.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    for attempt in range(ATTEMPTS):
        available = [m for m in MODEL_NAMES if m not in used_up]
        if not available:
            raise RuntimeError(
                "Today's free allowance is used up on every model. "
                "It resets within 24 hours."
            )
        for model in available:
            try:
                response = client.models.generate_content(
                    model=model, contents=prompt, config=config
                )
            except errors.APIError as e:
                if e.code not in BUSY_CODES:
                    raise
                if e.code == 429 and "PerDay" in str(e):
                    used_up.add(model)  # daily allowance gone; waiting will not help
                continue  # this model is busy, try the next one
            except httpx.TimeoutException:
                continue  # no reply in time, try the next one
            last_model = model
            return answer_format.model_validate_json(response.text)
        # Every model was busy. Wait a little longer each time, then retry.
        if attempt < ATTEMPTS - 1:
            time.sleep(WAIT_SECONDS * (attempt + 1))
    raise RuntimeError(
        f"The AI service was busy or silent on all {ATTEMPTS} attempts. "
        f"Try again in a few minutes."
    )
