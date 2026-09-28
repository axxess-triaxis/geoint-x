"""Single, replaceable LLM client boundary.

Only structured JSON calls validated against a pydantic schema are supported.
Every caller must handle ``LlmUnavailable`` by falling back to deterministic
output, so the product works fully with no API key and under quota exhaustion.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LlmUnavailable(RuntimeError):
    pass


class LlmClient(Protocol):
    model: str

    def generate_json(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
    ) -> T: ...


class GeminiClient:
    """google-genai ``models.generate_content`` with a JSON schema response."""

    def __init__(
        self, api_key: str, model: str, timeout_s: float = 45.0, max_retries: int = 2
    ) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000))
        )
        self.model = model
        self.max_retries = max_retries

    def generate_json(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
    ) -> T:
        types = self._types
        parts: list[object] = [types.Part.from_text(text=prompt)]
        for data, mime in images or []:
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
            temperature=0.2,
        )
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=self.model,
                    contents=[types.Content(role="user", parts=parts)],  # type: ignore[arg-type]
                    config=config,
                )
                text = resp.text or ""
                return schema.model_validate_json(text)
            except ValidationError as e:
                raise LlmUnavailable(f"model output failed schema validation: {e}") from e
            except Exception as e:  # network, 429, 5xx, timeout
                last_err = e
                msg = str(e)
                retryable = any(code in msg for code in ("429", "500", "503", "RESOURCE_EXHAUSTED"))
                log.warning("gemini call failed (attempt %s): %s", attempt + 1, msg[:200])
                if not retryable or attempt == self.max_retries:
                    break
                time.sleep(2 ** (attempt + 1))
        raise LlmUnavailable(f"gemini unavailable: {str(last_err)[:300]}")


# Why the LLM is (not) available, for operators. Never contains the key.
STATUS: dict[str, str] = {"status": "not initialised"}


def build_client(
    api_key: str | None, model: str, timeout_s: float, enabled: bool
) -> LlmClient | None:
    if not enabled:
        STATUS["status"] = "disabled by configuration"
        return None
    if not (api_key and api_key.strip()):
        STATUS["status"] = "no API key (variable missing or empty)"
        return None
    try:
        client = GeminiClient(api_key.strip(), model, timeout_s)
    except Exception as e:  # import/config failure
        log.warning("could not initialise Gemini client: %s", e)
        STATUS["status"] = f"client failed to start: {type(e).__name__}: {str(e)[:160]}"
        return None
    STATUS["status"] = "ready"
    return client
