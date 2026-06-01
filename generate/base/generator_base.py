import os
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

class GenerationClient:
    """
    Extension of the OpenAI chat wrapper tailored for the CAGE generation pipeline.
    Mirrors the pattern in evaluate/base/gpt_base.py with generation-specific features:
    - Structured JSON output for taxonomy classification
    - Slot-tagging and content localization
    - Cost tracking inherited from the evaluate module pattern
    """

    def __init__(self, model: str = "gpt-4.1", api_key: str = None):
        if api_key is None:
            api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY must be set as an environment variable "
                "or passed explicitly."
            )

        self.model = model
        self.client = OpenAI(api_key=api_key)

        # Per-token cost rates (USD per token)
        if "gpt-4.1-mini" in model:
            self.cost_per_prompt_token = 0.80 / 1_000_000
            self.cost_per_completion_token = 3.20 / 1_000_000
        elif "gpt-4.1" in model:
            self.cost_per_prompt_token = 3.0 / 1_000_000
            self.cost_per_completion_token = 12.0 / 1_000_000
        elif "gpt-4o-mini" in model:
            self.cost_per_prompt_token = 0.15 / 1_000_000
            self.cost_per_completion_token = 0.60 / 1_000_000
        elif "gpt-4o" in model:
            self.cost_per_prompt_token = 2.50 / 1_000_000
            self.cost_per_completion_token = 10.0 / 1_000_000
        else:
            self.cost_per_prompt_token = 10.0 / 1_000_000
            self.cost_per_completion_token = 30.0 / 1_000_000

        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.total_cost = 0.0

        self._original_create = self.client.chat.completions.create
        self._install_cost_hook()

    def _install_cost_hook(self):
        def _hooked_create(*args, **kwargs):
            completion = self._original_create(*args, **kwargs)
            if completion.usage is not None:
                usage = completion.usage
                self.prompt_tokens += usage.prompt_tokens
                self.completion_tokens += usage.completion_tokens
                self.total_tokens += usage.total_tokens
                cost_prompt = usage.prompt_tokens * self.cost_per_prompt_token
                cost_completion = usage.completion_tokens * self.cost_per_completion_token
                self.total_cost += (cost_prompt + cost_completion)
            return completion

        self.client.chat.completions.create = _hooked_create

    def generate(
        self,
        input_text: str,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Synchronous generation call."""
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": input_text},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return completion.choices[0].message.content

    def generate_json(
        self,
        input_text: str,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """Synchronous generation call with JSON structured output."""
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": input_text},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return completion.choices[0].message.content

    def reset_cost(self):
        """Reset usage counters."""
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.total_cost = 0.0
