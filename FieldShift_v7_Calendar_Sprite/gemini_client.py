"""Shared Gemini client settings for FieldShift.

Uses the same Google GenAI SDK, model family, and timeout pattern as the
standalone connection test. The key is never written to a file by this module.
"""
from __future__ import annotations

import os

DEFAULT_GEMINI_MODEL = os.getenv("FIELDSHIFT_GEMINI_MODEL", "gemini-3.5-flash-lite")


def generate_gemini_reply(api_key: str, prompt: str, model: str | None = None) -> str:
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Enter your Gemini API key or set GEMINI_API_KEY before requesting advice.")
    if any(c in key for c in "\r\n\t"):
        raise ValueError("The Gemini API key must be one line, with no embedded whitespace.")

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            'Gemini SDK missing. Run: python -m pip install --upgrade google-genai'
        ) from exc

    # 60s for a longer farm advisory prompt versus 30s for the simple test.
    # Configurable for slow connections without changing project code.
    timeout_ms = int(os.getenv("FIELDSHIFT_GEMINI_TIMEOUT_MS", "60000"))
    timeout_ms = max(10000, min(timeout_ms, 180000))
    model_name = (model or DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
    client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(timeout=timeout_ms),
    )
    try:
        answer = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=1600),
        )
        text = (answer.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned an empty text response; try again or change the model.")
        return text
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
