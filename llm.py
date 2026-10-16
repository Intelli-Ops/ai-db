"""
Shared AI model connection for the POC.
Every script that needs the AI imports ask() from here, so the model
name and the key handling live in one place.

The AI is reached through OpenRouter (https://openrouter.ai), a service
that gives one key and one way of asking for many different AI models.
The key is read from a file named .env in this folder:
    AI_API_KEY=your-key-here

We ask OpenRouter to use only providers that do not store or train on
what we send. Even so, real company table names need approval before
being sent.
"""
import os
import re
import time

import httpx
from dotenv import load_dotenv

URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_NAME = "nvidia/nemotron-3-ultra-550b-a55b"  # "NVIDIA: Nemotron 3 Ultra"

ATTEMPTS = 4
WAIT_SECONDS = 10
TIMEOUT_SECONDS = 180  # give up on a single reply after this long
# 408 = the request took too long; 429 = too many requests at once;
# 500/502/503/504 = OpenRouter or the model's provider is busy or down.
BUSY_CODES = {408, 429, 500, 502, 503, 504}

# Which model gave the most recent answer, so results can be traced.
last_model = None

load_dotenv()


def strict(schema):
    """
    Mark every object in the answer format as "these fields and no others".
    Strict structured output needs this, and pydantic leaves it out.
    """
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            schema["additionalProperties"] = False
        for value in schema.values():
            strict(value)
    elif isinstance(schema, list):
        for item in schema:
            strict(item)
    return schema


def ask(prompt, answer_format):
    """
    Send a prompt to the AI and get the answer back in a fixed shape.

    answer_format is a pydantic class describing the fields we expect.
    The AI is forced to reply in that shape, so we never have to pick
    an answer out of free-flowing text.
    """
    global last_model
    api_key = os.environ.get("AI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No AI key found. Create a file named .env in this folder "
            "containing the line:  AI_API_KEY=your-key-here"
        )
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        # The reply must be JSON that fits answer_format exactly.
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": answer_format.__name__,
                "strict": True,
                "schema": strict(answer_format.model_json_schema()),
            },
        },
        # As steady as possible: the same question should get the same answer.
        "temperature": 0,
        "provider": {
            # Only send to providers that can enforce the JSON shape above,
            # and that do not keep or train on what we send.
            "require_parameters": True,
            "data_collection": "deny",
        },
    }
    headers = {"Authorization": f"Bearer {api_key}", "X-Title": "AI Reporting POC"}

    for attempt in range(ATTEMPTS):
        try:
            response = httpx.post(URL, json=payload, headers=headers,
                                  timeout=TIMEOUT_SECONDS)
        except httpx.TimeoutException:
            problem = f"no reply within {TIMEOUT_SECONDS} seconds"
        else:
            data = response.json() if response.content else {}
            error = data.get("error") or (data.get("choices") or [{}])[0].get("error")
            if response.status_code == 200 and not error:
                last_model = data.get("model", MODEL_NAME)
                text = data["choices"][0]["message"]["content"]
                # Some models wrap JSON in ```json ... ``` even when asked not to.
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
                return answer_format.model_validate_json(text)

            code = (error or {}).get("code", response.status_code)
            message = (error or {}).get("message", response.text[:300])
            if code == 401:
                raise RuntimeError("OpenRouter rejected the key. Check AI_API_KEY in .env.")
            if code == 402:
                raise RuntimeError("The OpenRouter account has run out of credit.")
            if code not in BUSY_CODES:
                raise RuntimeError(f"OpenRouter error {code}: {message}")
            problem = f"busy (error {code})"

        # Busy or silent. Wait a little longer each time, then retry.
        if attempt < ATTEMPTS - 1:
            time.sleep(WAIT_SECONDS * (attempt + 1))
    raise RuntimeError(
        f"The AI service was busy or silent on all {ATTEMPTS} attempts "
        f"(last: {problem}). Try again in a few minutes."
    )
