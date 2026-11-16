"""The only place that talks to the Claude API. Agents call LLMClient.structured(); tests replace it."""

import logging
import time
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from app.config import Settings
from app.llm.pricing import cost_usd
from app.llm.prompts import load_prompt

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class LLMUsage:
    agent: str
    prompt: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens


@dataclass
class LLMResult(Generic[T]):
    output: T
    usage: LLMUsage


class LLMError(Exception):
    """Claude could not produce a usable answer (after the SDK's retries). Session state is kept."""

    user_message = "The AI interviewer is temporarily unavailable. Your progress is saved - please try again."

    def __init__(self, detail: str = "", usage: LLMUsage | None = None):
        super().__init__(detail or self.user_message)
        self.usage = usage


class LLMRefusalError(LLMError):
    user_message = "The AI interviewer could not respond to that message. Please rephrase and try again."


class LLM(Protocol):
    def structured(
        self,
        *,
        agent: str,
        prompt: str,
        messages: list[dict],
        output_model: type[T],
        effort: str,
        max_tokens: int = 8000,
    ) -> LLMResult[T]: ...


class LLMClient:
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None):
        self._settings = settings
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:  # created lazily so the app starts without a key
            self._client = anthropic.Anthropic(
                api_key=self._settings.anthropic_api_key or None,
                max_retries=2,  # NFR-11: retry 429 / 5xx up to 2 times
                timeout=60.0,
            )
        return self._client

    def structured(
        self,
        *,
        agent: str,
        prompt: str,
        messages: list[dict],
        output_model: type[T],
        effort: str,
        max_tokens: int = 8000,
    ) -> LLMResult[T]:
        model = self._settings.claude_model
        extra: dict = {}
        if self._settings.llm_fallbacks:
            extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}

        start = time.perf_counter()
        try:
            response = self.client.beta.messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=load_prompt(prompt),
                messages=messages,
                output_format=output_model,
                output_config={"effort": effort},
                cache_control={"type": "ephemeral"},
                **extra,
            )
        except anthropic.AuthenticationError as e:
            log.error("Claude authentication failed - check ANTHROPIC_API_KEY: %s", e)
            raise LLMError(str(e)) from e
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            log.warning("Claude call failed for %s after retries: %s", agent, e)
            raise LLMError(str(e)) from e
        except anthropic.AnthropicError as e:
            log.error("Claude client error for %s: %s", agent, e)
            raise LLMError(str(e)) from e
        except TypeError as e:
            if "authentication" not in str(e):
                raise
            log.error("No Claude credentials configured - set ANTHROPIC_API_KEY in backend/.env")
            raise LLMError("missing credentials") from e

        u = response.usage
        served_by = getattr(response, "model", None) or model
        usage = LLMUsage(
            agent=agent,
            prompt=prompt,
            model=served_by,
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
        usage.cost_usd = cost_usd(
            served_by, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens, usage.cache_write_tokens
        )
        log.info(
            "llm agent=%s prompt=%s model=%s in=%d out=%d cache_r=%d cache_w=%d ms=%d cost=$%.5f",
            agent, prompt, served_by, usage.input_tokens, usage.output_tokens,
            usage.cache_read_tokens, usage.cache_write_tokens, usage.latency_ms, usage.cost_usd,
        )

        if response.stop_reason == "refusal":
            raise LLMRefusalError(f"{agent} call refused", usage=usage)
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise LLMError(f"{agent} call returned no parsable output ({response.stop_reason})", usage=usage)
        return LLMResult(output=response.parsed_output, usage=usage)
