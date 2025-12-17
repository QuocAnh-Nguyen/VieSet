import os
from openai import OpenAI
from ..utils.logger import get_logger

logger = get_logger(__name__)

class OpenAIChat:
    def __init__(self, model: str = "gpt-4.1", api_key: str = None):
        if api_key is None:
            api_key = os.getenv("OPENAI_API_KEY")
            
        self.model = model
        self.client = OpenAI(api_key=api_key)

        # rate for cost calculation (update with latest model prices as needed)
        if 'gpt-4.1-mini' in model:
            self.cost_per_prompt_token = 0.80 / 1_000_000
            self.cost_per_completion_token = 3.20 / 1_000_000
        elif 'gpt-4.1' in model:
            self.cost_per_prompt_token = 3.0 / 1_000_000
            self.cost_per_completion_token = 12.0 / 1_000_000
        else:
            self.cost_per_prompt_token = 10.0 / 1_000_000
            self.cost_per_completion_token = 30.0 / 1_000_000

        # variable to track usage
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.total_cost = 0.0

        # save original create method
        self._original_create = self.client.chat.completions.create

        # install cost tracking hook
        self._install_cost_hook()

    def _install_cost_hook(self):
        """
        Internal method for installing cost tracking hook.
        - overrides self.client.chat.completions.create
        - post-processes usage info after calling the original create method.
        """
        def _hooked_create(*args, **kwargs):
            completion = self._original_create(*args, **kwargs)

            if completion.usage is not None:
                usage = completion.usage
                self.prompt_tokens = usage.prompt_tokens
                self.completion_tokens = usage.completion_tokens
                self.total_tokens = usage.total_tokens

                cost_for_prompt = self.prompt_tokens * self.cost_per_prompt_token
                cost_for_completion = self.completion_tokens * self.cost_per_completion_token
                self.total_cost += (cost_for_prompt + cost_for_completion) 

            return completion
        
        self.client.chat.completions.create = _hooked_create

    def generate_response(self, input_text: str, system_prompt: str = "You are a helpful assistant.") -> str:
        """
        Basic synchronous call method.        
        """
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": input_text}
            ],
        )
        return completion.choices[0].message.content