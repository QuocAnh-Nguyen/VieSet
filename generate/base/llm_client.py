"""
Unified LLM Client for the CAGE Generation Pipeline.

Wraps litellm.acompletion for provider-agnostic async generation with:
- Dynamic base_url for DeepSeek, local vLLM, and custom endpoints
- Built-in cost tracking via litellm.completion_cost()
- Exponential backoff + retry via tenacity
- JSON output with markdown-stripping

Replaces the tightly-coupled, synchronous, monkey-patched GenerationClient
and OpenAIChat classes.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

import litellm
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON markdown stripping regex
# ---------------------------------------------------------------------------
_JSON_FENCE_RE = re.compile(
    r'```(?:json)?\s*\n?(.*?)\n?```',
    re.DOTALL | re.IGNORECASE,
)


def strip_markdown_wrapper(raw: str) -> str:
    """Strip ```json ... ``` fences around a raw LLM response."""
    stripped = raw.strip()
    m = _JSON_FENCE_RE.search(stripped)
    return m.group(1).strip() if m else stripped


def parse_json(raw: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Strip markdown wrappers then parse JSON.

    Handles common LLM output quirks:
    - Markdown code fences with/without conversational filler
    - Trailing commas before closing brackets/braces

    Returns (success, parsed_dict_or_None, error_message).
    """
    cleaned = strip_markdown_wrapper(raw)

    # If strip_markdown_wrapper didn't find fences, try to extract
    # the first JSON object from anywhere in the text
    if cleaned == raw.strip():
        brace_match = re.search(r'\{(?:[^{}]|\{[^{}]*\})*\}', cleaned, re.DOTALL)
        if brace_match:
            cleaned = brace_match.group(0)

    try:
        data = json.loads(cleaned)
        return True, data, "OK"
    except json.JSONDecodeError as e:
        pass

    # Stage 2: fix trailing commas and retry
    try:
        fixed = re.sub(r',\s*([}\]])', r'\1', cleaned)
        data = json.loads(fixed)
        return True, data, "OK (trailing comma fixed)"
    except json.JSONDecodeError:
        pass

    # Stage 3: find any JSON object with relaxed matching
    try:
        relaxed = re.search(r'\{[^}]*"result"[^}]*\}', cleaned, re.DOTALL | re.IGNORECASE)
        if relaxed:
            data = json.loads(relaxed.group(0))
            return True, data, "OK (relaxed extraction)"
    except json.JSONDecodeError:
        pass

    return False, None, f"JSON decode error: {str(e) if 'e' in dir() else 'unknown'}"


# ---------------------------------------------------------------------------
# Retryable exceptions
# ---------------------------------------------------------------------------
_RETRYABLE = (
    litellm.exceptions.RateLimitError,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.InternalServerError,
    litellm.exceptions.Timeout,
)

_RETRYABLE_GENERIC_MESSAGES = (
    "rate limit",
    "502",
    "503",
    "bad gateway",
    "timeout",
)


def _is_retryable(exception: BaseException) -> bool:
    """Determine whether an exception should trigger a retry."""
    if isinstance(exception, _RETRYABLE):
        return True
    msg = str(exception).lower()
    return any(needle in msg for needle in _RETRYABLE_GENERIC_MESSAGES)


# ---------------------------------------------------------------------------
# LiteLLM configuration helpers
# ---------------------------------------------------------------------------

def _resolve_model_name(model: str, base_url: Optional[str] = None) -> str:
    """
    Resolve a short model name to litellm's prefixed form when a known
    base_url is supplied.

    Examples:
        model='deepseek-chat', base_url='https://api.deepseek.com'
            -> 'deepseek/deepseek-chat'
        model='gpt-4.1' -> 'gpt-4.1'  (OpenAI, no prefix needed)
        model='custom-model', base_url='http://localhost:8000/v1'
            -> 'openai/custom-model' (custom endpoint via OpenAI-compat)
    """
    if base_url is None:
        return model

    # DeepSeek detection
    if "deepseek" in model.lower() or (base_url and "deepseek.com" in base_url):
        if not model.startswith("deepseek/"):
            return f"deepseek/{model}"
        return model

    # Custom base_url with an unprefixed model -> route as openai/compat
    if "/" not in model:
        return f"openai/{model}"

    return model


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------
class LLMClient:
    """
    Unified, async-first LLM client for multi-provider generation.

    Uses litellm under the hood for:
    - Provider routing (OpenAI, DeepSeek, Anthropic, Gemini, vLLM, ...)
    - Automatic cost tracking via ``litellm.completion_cost()``
    - Consistent chat-completion interface

    Parameters
    ----------
    model : str
        LiteLLM-compatible model string.  Use:
        * ``'gpt-4.1'`` for OpenAI
        * ``'deepseek/deepseek-chat'`` for DeepSeek (or set base_url)
        * ``'openai/custom-model'`` with ``base_url`` for local vLLM
    api_key : str, optional
        API key.  If omitted, litellm searches environment variables
        (``OPENAI_API_KEY``, ``DEEPSEEK_API_KEY``, etc.).
    base_url : str, optional
        Custom base URL for OpenAI-compatible endpoints
        (DeepSeek, vLLM, Ollama, etc.).
    """

    def __init__(
        self,
        model: str = "gpt-4.1",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.model = _resolve_model_name(model, base_url)
        self.api_key = api_key
        self.base_url = base_url

        # Accumulators
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.total_cost: float = 0.0

        logger.info(
            "LLMClient initialized: model=%s base_url=%s",
            self.model,
            base_url,
        )

    # -- internal helpers --------------------------------------------------

    def _track_usage(self, response: Any) -> None:
        """Extract token usage & cost from a litellm response object."""
        try:
            usage = (
                response.get("usage", None)
                if isinstance(response, dict)
                else getattr(response, "usage", None)
            )
            if usage is not None:
                prompt = (
                    usage.get("prompt_tokens", 0)
                    if isinstance(usage, dict)
                    else getattr(usage, "prompt_tokens", 0)
                )
                completion = (
                    usage.get("completion_tokens", 0)
                    if isinstance(usage, dict)
                    else getattr(usage, "completion_tokens", 0)
                )
                total = (
                    usage.get("total_tokens", 0)
                    if isinstance(usage, dict)
                    else getattr(usage, "total_tokens", 0)
                )
                self.prompt_tokens += prompt
                self.completion_tokens += completion
                self.total_tokens += total
        except Exception:
            logger.debug("Could not extract usage from response", exc_info=True)

        try:
            cost = litellm.completion_cost(completion_response=response)
            if cost and cost > 0:
                self.total_cost += cost
        except Exception:
            logger.debug("Could not compute cost via litellm", exc_info=True)

    def _build_kwargs(
        self,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """Build the common kwargs dict for a litellm call."""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["api_base"] = self.base_url
        return kwargs

    # -- retry wrapper -----------------------------------------------------

    def _retry_decorator(self):
        """Return a tenacity retry decorator with exponential backoff."""
        return retry(
            retry=retry_if_exception_type(_RETRYABLE)
            | retry_if_exception_type(Exception),
            wait=wait_exponential_jitter(initial=1, max=60, jitter=2),
            stop=stop_after_attempt(5),
            before_sleep=lambda retry_state: logger.warning(
                "LLM call attempt %d failed: %s. Retrying in %.1fs...",
                retry_state.attempt_number,
                (
                    retry_state.outcome.exception()
                    if retry_state.outcome
                    else "unknown"
                ),
                (
                    retry_state.next_action.sleep
                    if retry_state.next_action
                    else 0
                ),
            ),
            after=lambda retry_state: logger.info(
                "LLM call succeeded on attempt %d",
                retry_state.attempt_number,
            ),
        )

    # -- async generation --------------------------------------------------

    async def agenerate(
        self,
        input_text: str,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Async text generation with retry."""
        kwargs = self._build_kwargs(system_prompt, temperature, max_tokens)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ]

        @self._retry_decorator()
        async def _call():
            return await litellm.acompletion(messages=messages, **kwargs)

        response = await _call()
        self._track_usage(response)
        return response["choices"][0]["message"]["content"]

    async def agenerate_json(
        self,
        input_text: str,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """
        Async JSON-structured generation with retry.

        Ensures the system prompt contains the word 'JSON' to satisfy
        litellm/OpenAI strict-JSON-mode requirements.
        """
        # Inject 'JSON' keyword if missing (required by strict-JSON mode)
        if "json" not in system_prompt.lower():
            system_prompt = (
                system_prompt + "\n\nYou must respond with valid JSON only."
            )

        kwargs = self._build_kwargs(system_prompt, temperature, max_tokens)
        kwargs["response_format"] = {"type": "json_object"}
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ]

        @self._retry_decorator()
        async def _call():
            return await litellm.acompletion(messages=messages, **kwargs)

        response = await _call()
        self._track_usage(response)
        return response["choices"][0]["message"]["content"]

    # -- synchronous convenience wrappers ----------------------------------

    def generate(
        self,
        input_text: str,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Synchronous text generation. Prefer ``agenerate`` in async contexts."""
        kwargs = self._build_kwargs(system_prompt, temperature, max_tokens)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ]

        @self._retry_decorator()
        def _call():
            return litellm.completion(messages=messages, **kwargs)

        response = _call()
        self._track_usage(response)
        return response["choices"][0]["message"]["content"]

    def generate_json(
        self,
        input_text: str,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """Synchronous JSON gen. Prefer ``agenerate_json`` in async contexts."""
        if "json" not in system_prompt.lower():
            system_prompt = (
                system_prompt + "\n\nYou must respond with valid JSON only."
            )

        kwargs = self._build_kwargs(system_prompt, temperature, max_tokens)
        kwargs["response_format"] = {"type": "json_object"}
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ]

        @self._retry_decorator()
        def _call():
            return litellm.completion(messages=messages, **kwargs)

        response = _call()
        self._track_usage(response)
        return response["choices"][0]["message"]["content"]

    # -- cost / usage ------------------------------------------------------

    def reset_cost(self) -> None:
        """Reset all usage counters to zero."""
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.total_cost = 0.0

    @property
    def usage_summary(self) -> Dict[str, Any]:
        """Return a dict summarizing token and cost usage."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost, 6),
        }


# ---------------------------------------------------------------------------
# Backward-compatible wrapper
# ---------------------------------------------------------------------------
class GenerationClient(LLMClient):
    """
    Backward-compatible alias for ``LLMClient``.

    Existing code that imports ``GenerationClient`` from
    ``generate.base`` will continue to work unchanged.
    """

    pass
