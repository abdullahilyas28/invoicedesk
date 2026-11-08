"""Thin wrapper around the LLM provider. The rest of InvoiceDesk only calls generate()."""
import os
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

import random
from google.genai import errors

load_dotenv()

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
REQUESTS_PER_MINUTE = int(os.environ.get("GEMINI_RPM", "15"))
MAX_ATTEMPTS = 4
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

client = genai.Client()


@dataclass
class LLMResult:
    text: str
    parsed: BaseModel | None
    model: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float

_last_call_time = 0.0


def _wait_for_rate_limit() -> None:
    """
    Sleep just long enough to stay under REQUESTS_PER_MINUTE.
    """
    global _last_call_time
    min_gap_seconds = 60 / REQUESTS_PER_MINUTE
    elapsed = time.monotonic() - _last_call_time
    if elapsed < min_gap_seconds:
        time.sleep(min_gap_seconds - elapsed)
    _last_call_time = time.monotonic()

def generate(prompt: str, file_path: str | Path | None = None, schema: type[BaseModel] | None = None, model: str = MODEL_NAME) -> LLMResult:
    """
    Send a prompt, plus an optional PDF or image, to the model.

    If a Pydantic schema is given, the model must return JSON matching it,
    and result.parsed holds the validated object.
    """
    contents = []
    if file_path is not None:
        file_path = Path(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        contents.append(types.Part.from_bytes(data=file_path.read_bytes(), mime_type=mime_type))
    contents.append(prompt)

    config = None
    if schema is not None:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        )

    start_time = time.perf_counter()
    response = _call_with_retry(model, contents, config)
    latency_seconds = time.perf_counter() - start_time

    usage = response.usage_metadata
    return LLMResult(
        text=response.text or "",
        parsed=response.parsed if schema is not None else None,
        model=model,
        input_tokens=usage.prompt_token_count or 0,
        output_tokens=usage.candidates_token_count or 0,
        latency_seconds=latency_seconds,
    )

def call_model(contents: list, config: types.GenerateContentConfig, model: str = MODEL_NAME) -> tuple[types.GenerateContentResponse, int, int, float]:
    """
    One raw model turn for multi-turn tool use. Returns (response, input_tokens, output_tokens, latency).
    """
    start_time = time.perf_counter()
    response = _call_with_retry(model, contents, config)
    latency_seconds = time.perf_counter() - start_time
    usage = response.usage_metadata
    return response, usage.prompt_token_count or 0, usage.candidates_token_count or 0, latency_seconds

def _call_with_retry(model: str, contents: list, config: types.GenerateContentConfig | None):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _wait_for_rate_limit()
        try:
            return client.models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as error:
            if error.code not in RETRYABLE_STATUS_CODES or attempt == MAX_ATTEMPTS:
                raise
            backoff_seconds = 2 ** attempt + random.uniform(0, 1)
            print(f"  [llm] error {error.code} on attempt {attempt}, retrying in {backoff_seconds:.1f}s")
            time.sleep(backoff_seconds)