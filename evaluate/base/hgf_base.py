"""
HuggingFace base model wrapper for local LLM inference.

Phase 1 Refactor:
- Fixed device_map="auto" tensor mismatch: use model.device or
  find the device of the first parameter instead of hardcoding "cuda".
"""

from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
from ..utils.logger import get_logger

logger = get_logger(__name__)


class HGFBase:
    """Local HuggingFace LLM wrapper (evaluate pipeline)."""

    def __init__(self, llm: str) -> None:
        if "awq" in llm.lower():  # AWQ Quantization
            from awq import AutoAWQForCausalLM

            self.model = AutoAWQForCausalLM.from_quantized(
                llm,
                torch_dtype=torch.float16,
                low_cpu_mem_usage=True,
                fuse_layers=True,
                use_cache=True,
                no_repeat_ngram=10,
                device_map="auto",
            )
        else:
            self.model = AutoModelForCausalLM.from_pretrained(
                llm,
                torch_dtype=torch.bfloat16,
                trust_remote_code=True,
                device_map="auto",
            )
            self.model.config.use_cache = True

        self.tokenizer = AutoTokenizer.from_pretrained(llm)
        self.llm_name = llm
        self.total_cost = 0.0

        # Determine the device of the first parameter so we can
        # move input tensors to the same device, avoiding a
        # RuntimeError when device_map="auto" spreads layers
        # across multiple GPUs / CPU.
        try:
            self._device = next(self.model.parameters()).device
        except StopIteration:
            self._device = torch.device("cpu")
        logger.info("HGFBase initialized on device: %s", self._device)

    def __call__(self, prompt: str, schema=None) -> str:
        # Build messages
        if "gemma" in self.llm_name.lower():
            messages = [{"role": "user", "content": prompt}]
        elif schema is not None:
            messages = [
                {"role": "system", "content": f"Here is some context:

{schema}"},
                {"role": "user", "content": prompt},
            ]
        else:
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ]

        input_ids = self.tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        )

        # Use the detected device rather than hardcoded "cuda"
        input_ids = input_ids.to(self._device)

        output = self.model.generate(
            input_ids,
            eos_token_id=self.tokenizer.eos_token_id,
            max_new_tokens=2048,
        )
        return self.tokenizer.decode(
            output[0], skip_special_tokens=True
        ).replace(
            self.tokenizer.decode(input_ids[0], skip_special_tokens=True), ""
        )
