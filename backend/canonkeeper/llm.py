"""Thin wrapper over the Gemini Interactions API."""
from __future__ import annotations

import asyncio
import base64
import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Type, TypeVar

from google import genai
from pydantic import BaseModel, ValidationError

from . import config, store

T = TypeVar("T", bound=BaseModel)
_client: Optional[genai.Client] = None


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GOOGLE_API_KEY)
    return _client


@dataclass
class Result:
    text: str
    interaction_id: str
    input_tokens: int
    output_tokens: int
    raw: Any
    parsed: Any = None


def text_part(text: str) -> dict:
    return {"type": "text", "text": text}


def image_part(ref: str) -> dict:
    data, mime = store.assets().get(ref)
    return {"type": "image", "data": base64.b64encode(data).decode(), "mime_type": mime}


def document_part(ref: str) -> dict:
    data, mime = store.assets().get(ref)
    return {"type": "document", "data": base64.b64encode(data).decode(), "mime_type": mime}


def media_part(ref: str) -> dict:
    _, mime = store.assets().get(ref)
    return document_part(ref) if mime == "application/pdf" else image_part(ref)


def parse_json(text: str) -> Any:
    if not text:
        raise ValueError("empty model response")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(cleaned)


def _create(model: str, parts: list[dict], *, schema: Optional[Type[BaseModel]], previous: Optional[str],
            thinking: str, max_output_tokens: Optional[int]):
    kwargs: dict = {"model": model, "input": parts}
    gen: dict = {"thinking_level": thinking}
    if max_output_tokens:
        gen["max_output_tokens"] = max_output_tokens
    kwargs["generation_config"] = gen
    if previous:
        kwargs["previous_interaction_id"] = previous
    if schema is not None:
        kwargs["response_format"] = {"type": "text", "mime_type": "application/json",
                                     "schema": schema.model_json_schema()}
    return client().interactions.create(**kwargs)


def _usage(interaction) -> tuple[int, int]:
    u = getattr(interaction, "usage", None)
    if not u:
        return 0, 0
    return int(u.total_input_tokens or 0), int(u.total_output_tokens or 0)


def generate_sync(model: str, parts: list[dict], *, schema: Optional[Type[T]] = None,
                  previous: Optional[str] = None, thinking: str = "low",
                  max_output_tokens: Optional[int] = None, retries: int = 2) -> Result:
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            it = _create(model, parts, schema=schema, previous=previous, thinking=thinking,
                         max_output_tokens=max_output_tokens)
            text = it.output_text or ""
            parsed = None
            if schema is not None:
                data = parse_json(text)
                parsed = schema.model_validate(data)
            tin, tout = _usage(it)
            return Result(text=text, interaction_id=it.id or "", input_tokens=tin,
                          output_tokens=tout, raw=it, parsed=parsed)
        except (ValueError, ValidationError, json.JSONDecodeError) as exc:
            last = exc            # malformed output → ask again
        except Exception as exc:  # transient API errors
            last = exc
            if "not found" in str(exc).lower() and previous:
                raise            # expired context: caller refreshes it
    raise RuntimeError(f"{model} failed after {retries + 1} attempts: {last}")


async def generate(model: str, parts: list[dict], timeout: float | None = None, **kwargs) -> Result:
    """timeout: seconds per attempt; a runaway generation is abandoned and retried once."""
    if timeout is None:
        return await asyncio.to_thread(generate_sync, model, parts, **kwargs)
    last: Exception | None = None
    for _ in range(2):
        try:
            return await asyncio.wait_for(asyncio.to_thread(generate_sync, model, parts, retries=0, **kwargs), timeout)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"{model} did not finish: {last}")


def generate_image_sync(parts: list[dict]) -> tuple[bytes, str]:
    it = client().interactions.create(model=config.MODEL_IMAGE, input=parts)
    img = getattr(it, "output_image", None)
    if not img or not getattr(img, "data", None):
        raise RuntimeError(f"{config.MODEL_IMAGE} returned no image")
    raw = base64.b64decode(img.data) if isinstance(img.data, str) else img.data
    return raw, getattr(img, "mime_type", None) or "image/jpeg"


async def generate_image(parts: list[dict]) -> tuple[bytes, str]:
    return await asyncio.to_thread(generate_image_sync, parts)
