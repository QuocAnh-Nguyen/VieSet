"""
Safety Judge for VieSet / CAGE red-teaming prompts.

Evaluates prompt/response harmfulness using Vietnamese safety rubrics.

Phase 1 Refactor:
- Uses ``AsyncOpenAI`` natively instead of ``run_in_executor``.
- Robust JSON parsing with markdown-stripping.
- Case-insensitive regex fallback.
"""

import asyncio
import os
import argparse
import json
import logging
import sys
import re
import importlib

import pandas as pd
from openai import AsyncOpenAI

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", "logs"))
os.makedirs(LOG_DIR, exist_ok=True)

# Error log path setting (/logs/judge_errors)
ERROR_LOG_PATH = os.path.join(LOG_DIR, "judge_errors")
os.makedirs(ERROR_LOG_PATH, exist_ok=True)

# Logging configuration (console + file)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)

# ---------------------------------------------------------------------------
# JSON markdown stripping (mirrors llm_client.py)
# ---------------------------------------------------------------------------
_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?(.*?)\n?```\s*$",
    re.DOTALL | re.IGNORECASE,
)


def _strip_markdown(raw: str) -> str:
    stripped = raw.strip()
    m = _JSON_FENCE_RE.match(stripped)
    return m.group(1).strip() if m else stripped


def parse_result_from_json(json_str: str) -> str:
    """
    Extracts the 'result' value from the JSON string. (O or X)

    Uses json.loads first, then a robust regex fallback.
    """
    cleaned = _strip_markdown(json_str)
    try:
        data = json.loads(cleaned)
        return data.get("result", "Error")
    except json.JSONDecodeError:
        # Robust regex: case-insensitive, handles whitespace/newlines
        match = re.search(r'"result"\s*:\s*"(o|x)"', cleaned, re.IGNORECASE)
        if match:
            return match.group(1).upper()
        return "Error"
    except Exception:
        return "Error"


# ---------------------------------------------------------------------------
# Async Judge (native AsyncOpenAI)
# ---------------------------------------------------------------------------
class CustomJudge:
    """
    Async safety judge using OpenAI SDK natively.

    Replaces the ``run_in_executor`` anti-pattern with a proper async client.
    """

    def __init__(self, model: str = "gpt-4.1", api_key: str = None) -> None:
        if api_key is None:
            api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY must be set or passed explicitly")

        self.model = model
        self.client = AsyncOpenAI(api_key=api_key)

    async def judge(self, system_prompt: str, user_prompt: str) -> str:
        """Async safety evaluation call."""
        try:
            comp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            return comp.choices[0].message.content or "{}"
        except Exception as e:
            logging.error(f"Judge Error: {e}")
            return "{}"


# ---------------------------------------------------------------------------
# Task processor
# ---------------------------------------------------------------------------
async def process_prompt(
    idx: int,
    user_prompt: str,
    system_prompt: str,
    judge_model: CustomJudge,
) -> dict:
    try:
        response_text = await judge_model.judge(system_prompt, user_prompt)
        result_val = parse_result_from_json(response_text)
        return {"raw_output": response_text, "result": result_val}
    except Exception as e:
        logging.error(f"Error processing prompt {idx}: {e}")
        return {"raw_output": str(e), "result": "Error"}


# ---------------------------------------------------------------------------
# Main async orchestrator
# ---------------------------------------------------------------------------
async def main_async(
    input_csv: str,
    output_dir: str,
    output_filename: str,
    prompt_col: str,
    response_col: str,
    category_col: str,
    mode: str,
    lang: str,
    model: str,
    api_key: str,
    max_concurrency: int = 10,
):
    # 1. Load data
    if not os.path.exists(input_csv):
        raise FileNotFoundError(f"Input file not found: {input_csv}")

    logging.info(f"Loading data from {input_csv}...")
    df = pd.read_csv(input_csv, keep_default_na=False)

    # 2. Dynamic module loading
    module_name = "prompt_guard" if mode == "prompt" else "prompt_response_guard"
    module_path = f"evaluate.template.{lang}.{module_name}"

    logging.info(f"Importing module: {module_path}")
    try:
        target_module = importlib.import_module(module_path)
    except ImportError as e:
        raise ImportError(
            f"Failed to import module {module_path}. "
            f"Check if the file exists and path is correct. Error: {e}"
        )

    class_name = (
        "Prompt_Harmfulness"
        if mode == "prompt"
        else "Prompt_Response_Harmfulness"
    )

    PrompterClass = getattr(target_module, class_name)
    SYSTEM_PROMPT = getattr(target_module, "SYSTEM_PROMPT")

    prompter = PrompterClass()

    # 3. Generate prompts
    logging.info("Generating prompts...")
    prompts_list = df[prompt_col].tolist()
    categories_list = (
        df[category_col].tolist()
        if category_col in df.columns
        else ["A"] * len(df)
    )

    if mode == "prompt":
        user_prompts = prompter.generate_promptchunks(prompts_list, categories_list)
    else:
        if response_col not in df.columns:
            raise ValueError(
                f"Response column '{response_col}' not found in input CSV."
            )
        responses_list = df[response_col].tolist()
        user_prompts = prompter.generate_promptchunks(
            prompts_list, responses_list, categories_list
        )

    # 4. Initialize Judge model
    logging.info(f"Initializing Judge Model: {model}")
    judge_model = CustomJudge(model=model, api_key=api_key)

    # 5. Run with bounded concurrency via semaphore
    logging.info(
        f"Starting evaluation for {len(user_prompts)} items "
        f"(max concurrency={max_concurrency})..."
    )

    sem = asyncio.Semaphore(max_concurrency)

    async def bounded_process(idx: int, prompt: str) -> dict:
        async with sem:
            return await process_prompt(idx, prompt, SYSTEM_PROMPT, judge_model)

    tasks = [
        bounded_process(i, p) for i, p in enumerate(user_prompts)
    ]
    results = await asyncio.gather(*tasks)

    # 6. Organize and save results
    results_df = pd.DataFrame(results)
    out_df = pd.concat([df, results_df], axis=1)

    # Add columns in the style of judge_ours_rubric.py
    out_df["judge"] = out_df["result"].apply(lambda x: "Yes" if x == "X" else "No")
    out_df["safe_rubric"] = out_df["result"].apply(
        lambda x: "No" if x == "X" else "Yes"
    )

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)
    out_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    logging.info(f"Evaluation complete. Results saved to {output_path}")

    # Print simple statistics
    total = len(out_df)
    unsafe_count = len(out_df[out_df["result"] == "X"])
    safe_count = len(out_df[out_df["result"] == "O"])
    error_count = len(out_df[out_df["result"] == "Error"])

    logging.info(
        f"Total: {total}, Safe(O): {safe_count}, "
        f"Unsafe(X): {unsafe_count}, Error: {error_count}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Refactored Judge Script for Prompt/Response Harmfulness"
    )

    parser.add_argument(
        "--input", "-i", required=True, help="Input CSV file path"
    )
    parser.add_argument(
        "--outdir", "-d", required=True, help="Output directory"
    )
    parser.add_argument(
        "--outfile", "-o", required=True, help="Output filename"
    )

    parser.add_argument(
        "--prompt_col", "-pc",
        default="seed",
        help="Column name for prompt (default: seed)",
    )
    parser.add_argument(
        "--response_col", "-rc",
        default="response",
        help="Column name for response (default: response)",
    )
    parser.add_argument(
        "--category_col", "-cc",
        default="category",
        help="Column name for category (default: category)",
    )

    parser.add_argument(
        "--mode", "-m",
        required=True,
        choices=["prompt", "response"],
        help="Evaluation mode: prompt or response",
    )
    parser.add_argument(
        "--lang", "-l",
        required=True,
        choices=["en", "ko", "vn"],
        help="Language: en, ko, or vn",
    )

    parser.add_argument(
        "--model",
        default="gpt-4.1",
        help="Judge model name (default: gpt-4.1)",
    )
    parser.add_argument(
        "--api_key", "-a", required=True, help="OpenAI API Key"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Max concurrent judge calls (default: 10)",
    )

    args = parser.parse_args()

    asyncio.run(
        main_async(
            input_csv=args.input,
            output_dir=args.outdir,
            output_filename=args.outfile,
            prompt_col=args.prompt_col,
            response_col=args.response_col,
            category_col=args.category_col,
            mode=args.mode,
            lang=args.lang,
            model=args.model,
            api_key=args.api_key,
            max_concurrency=args.concurrency,
        )
    )


if __name__ == "__main__":
    main()
