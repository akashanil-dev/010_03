"""LLM provider switch. Local Granite via Ollama by default; IBM watsonx optional."""

import json
import os
import time

from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "ollama")

MODEL_NAMES = {   # friendly names for the badge in the header
    "granite4:micro": "IBM Granite 4.0 Micro (3B)",
    "granite3.3:2b": "IBM Granite 3.3 (2B)",
    "ibm/granite-3-8b-instruct": "IBM Granite 3 (8B)",
}


def model_info() -> dict:
    """Which model reads the documents, and where it runs."""
    if PROVIDER == "watsonx":
        model = os.getenv("WATSONX_MODEL", "ibm/granite-3-8b-instruct")
        return {"model": MODEL_NAMES.get(model, model), "where": "IBM watsonx (cloud)", "local": False}
    model = os.getenv("OLLAMA_MODEL", "granite4:micro")
    return {"model": MODEL_NAMES.get(model, model), "where": "on our server", "local": True}


def complete_json(prompt: str, schema: dict, on_chars=None) -> dict:
    """Ask the model for a JSON object that follows `schema`.

    on_chars(n), if given, is called as the answer streams in with the characters received so far
    (local model only), so the page can show how far along the extraction is.
    """
    if PROVIDER == "watsonx":
        return _watsonx(prompt, schema)
    return _ollama(prompt, schema, on_chars)


def _ollama(prompt: str, schema: dict, on_chars=None) -> dict:
    import ollama

    client = ollama.Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    parts, last = [], 0.0
    for chunk in client.chat(
        model=os.getenv("OLLAMA_MODEL", "granite4:micro"),
        messages=[{"role": "user", "content": prompt}],
        format=schema,
        options={"temperature": 0, "num_ctx": 8192},
        stream=True,
    ):
        parts.append(chunk["message"]["content"])
        if on_chars and time.monotonic() - last > 1:
            last = time.monotonic()
            on_chars(sum(map(len, parts)))
    return json.loads("".join(parts))


def _watsonx(prompt: str, schema: dict) -> dict:
    from ibm_watsonx_ai import Credentials
    from ibm_watsonx_ai.foundation_models import ModelInference

    model = ModelInference(
        model_id=os.getenv("WATSONX_MODEL", "ibm/granite-3-8b-instruct"),
        credentials=Credentials(url=os.getenv("WATSONX_URL"), api_key=os.getenv("WATSONX_API_KEY")),
        project_id=os.getenv("WATSONX_PROJECT_ID"),
        params={"temperature": 0, "max_new_tokens": 1200},
    )
    text = model.chat(messages=[{
        "role": "user",
        "content": prompt + "\n\nReply with only a JSON object matching this schema:\n" + json.dumps(schema),
    }])["choices"][0]["message"]["content"]
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])
