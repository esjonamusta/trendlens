"""
Provider-agnostic LLM client built on instructor for structured outputs.

Supports Anthropic and OpenAI with:
- Automatic structured output parsing via instructor
- Configurable retry logic via tenacity
- Prompt caching for Anthropic (reduces cost on long system prompts)
- Detailed logging of every call
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Type, TypeVar

import anthropic
import instructor
import openai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logger import get_logger

if TYPE_CHECKING:
    from pydantic import BaseModel

log = get_logger(__name__)

T = TypeVar("T", bound="BaseModel")

# Exceptions that are worth retrying
_RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.InternalServerError,
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.InternalServerError,
)


def _build_anthropic_client() -> instructor.Instructor:
    raw = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return instructor.from_anthropic(raw)


def _build_openai_client() -> instructor.AsyncInstructor:
    raw = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    return instructor.from_openai(raw)


class LLMClient:
    """
    Thin, production-ready wrapper around instructor-patched LLM clients.

    Usage:
        client = LLMClient()
        result = await client.complete(
            system_prompt="You are ...",
            user_prompt="Analyse ...",
            response_model=MyOutputSchema,
        )
    """

    def __init__(self) -> None:
        self._provider = settings.llm_provider
        self._model = settings.active_model
        self._temperature = settings.temperature
        self._max_tokens = settings.max_tokens

        if self._provider == "anthropic":
            self._client = _build_anthropic_client()
        else:
            self._client = _build_openai_client()

        log.info(
            "LLMClient initialised",
            extra={"provider": self._provider, "model": self._model},
        )

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        context_label: str = "llm_call",
    ) -> T:
        """
        Send a structured completion request and return a validated Pydantic model.

        Args:
            system_prompt: The agent's character and rules.
            user_prompt:   The specific task for this call.
            response_model: The Pydantic model to parse the response into.
            temperature:   Override the default temperature for this call.
            max_tokens:    Override the default max_tokens for this call.
            context_label: Label used in logs to identify the call.

        Returns:
            An instance of response_model populated from the LLM response.
        """
        t0 = time.perf_counter()

        resolved_model = model or self._model

        @retry(
            retry=retry_if_exception_type(_RETRYABLE),
            stop=stop_after_attempt(settings.max_retries),
            wait=wait_exponential(
                min=settings.retry_wait_min,
                max=settings.retry_wait_max,
            ),
            reraise=True,
        )
        async def _call() -> T:
            if self._provider == "anthropic":
                return await self._anthropic_call(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_model=response_model,
                    temperature=temperature or self._temperature,
                    max_tokens=max_tokens or self._max_tokens,
                    model=resolved_model,
                )
            return await self._openai_call(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
                temperature=temperature or self._temperature,
                max_tokens=max_tokens or self._max_tokens,
                model=resolved_model,
            )

        try:
            result = await _call()
            elapsed = time.perf_counter() - t0
            log.info(
                f"[{context_label}] completed in {elapsed:.2f}s "
                f"({self._provider}/{self._model})"
            )
            return result
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            log.error(
                f"[{context_label}] failed after {elapsed:.2f}s: {exc}",
                exc_info=True,
            )
            raise

    async def _anthropic_call(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        temperature: float,
        max_tokens: int,
        model: str,
    ) -> T:
        # Anthropic's prompt caching: mark the (long) system prompt as cacheable.
        # The API will serve subsequent identical calls from cache, reducing latency + cost.
        system_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        return await self._client.messages.create(  # type: ignore[union-attr]
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_blocks,  # type: ignore[arg-type]
            messages=[{"role": "user", "content": user_prompt}],
            response_model=response_model,
        )

    async def _openai_call(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        temperature: float,
        max_tokens: int,
        model: str,
    ) -> T:
        return await self._client.chat.completions.create(  # type: ignore[union-attr]
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_model=response_model,
        )


# ── Shared singleton ────────────────────────────────────────────────────────────
# Agents import this rather than constructing their own clients.
llm_client = LLMClient()
