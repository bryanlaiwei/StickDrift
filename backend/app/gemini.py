"""The one Gemini client, shared by the assistant and the clinician report.

GEMINI_API_KEY in backend/.env turns it on. An overloaded or rate-limited model
falls through to the next one in the list; any other error is raised.
"""
import logging
import os
import threading
from typing import Any, Dict

log = logging.getLogger(__name__)

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
# Tried in order when the primary model is overloaded or rate-limited.
FALLBACKS = ["gemini-3.5-flash", "gemini-flash-latest"]
RETRY_CODES = (429, 500, 503)

_clients: Dict[int, Any] = {}
_lock = threading.Lock()


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _client(timeout_ms: int):
    from google import genai
    from google.genai import types

    with _lock:
        if timeout_ms not in _clients:
            _clients[timeout_ms] = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                                                http_options=types.HttpOptions(timeout=timeout_ms))
        return _clients[timeout_ms]


def generate(contents, config, timeout_ms: int = 30000) -> str:
    """The answer's text (thoughts left out), from the first model that responds."""
    from google.genai import errors as genai_errors

    client = _client(timeout_ms)
    models = [MODEL] + [m for m in FALLBACKS if m != MODEL]
    for i, model in enumerate(models):
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
            break
        except genai_errors.APIError as e:
            if e.code not in RETRY_CODES or i == len(models) - 1:
                raise
            log.warning("Gemini %s returned %s, trying %s", model, e.code, models[i + 1])
    return "".join(p.text for p in (resp.candidates[0].content.parts or [])
                   if getattr(p, "text", None) and not getattr(p, "thought", False))
