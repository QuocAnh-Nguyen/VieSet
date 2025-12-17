import asyncio
import os
import argparse
import json
import logging
import sys
import pandas as pd
import re
import importlib

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from evaluate.base.gpt_base import OpenAIChat

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "../logs"))
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
        # logging.FileHandler(os.path.join(LOG_DIR, "safety_judge.log"))
    ]
)

class CustomJudge(OpenAIChat):
    async def judge(self, system_prompt: str, user_prompt: str) -> str:
        loop = asyncio.get_running_loop()
        try:
            comp = await loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.0,
                    max_tokens=1024,
                    response_format={"type": "json_object"} 
                )
            )
            return comp.choices[0].message.content
        except Exception as e:
            logging.error(f"Judge Error: {e}")
            return "{}"

def parse_result_from_json(json_str: str) -> str:
    """
    Extracts the 'result' value from the JSON string. (O or X)
    """
    try:
        data = json.loads(json_str)
        return data.get('result', 'Error')
    except json.JSONDecodeError:
        match = re.search(r'"result"\s*:\s*"(O|X)"', json_str)
        if match:
            return match.group(1)
        return 'Error'
    except Exception:
        return 'Error'

async def process_prompt(idx: int, user_prompt: str, system_prompt: str, judge_model: CustomJudge) -> dict:
    try:
        response_text = await judge_model.judge(system_prompt, user_prompt)
        result_val = parse_result_from_json(response_text)
        
        return {
            'raw_output': response_text,
            'result': result_val
        }
    except Exception as e:
        logging.error(f"Error processing prompt {idx}: {e}")
        return {'raw_output': str(e), 'result': 'Error'}

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
    api_key: str
):
    # 1. Load data
    if not os.path.exists(input_csv):
        raise FileNotFoundError(f"Input file not found: {input_csv}")
    
    logging.info(f"Loading data from {input_csv}...")
    df = pd.read_csv(input_csv, keep_default_na=False)

    # 2. Dynamic module loading
    # mode: 'prompt' -> prompt_guard.py / 'response' -> prompt_response_guard.py
    # lang: 'en' / 'ko'
    module_name = "prompt_guard" if mode == 'prompt' else "prompt_response_guard"
    module_path = f"evaluate.template.{lang}.{module_name}"
    
    logging.info(f"Importing module: {module_path}")
    try:
        target_module = importlib.import_module(module_path)
    except ImportError as e:
        raise ImportError(f"Failed to import module {module_path}. Check if the file exists and path is correct. Error: {e}")

    # Get class and system prompt
    # Class name convention: Prompt_Harmfulness (prompt mode), Prompt_Response_Harmfulness (response mode)
    class_name = "Prompt_Harmfulness" if mode == 'prompt' else "Prompt_Response_Harmfulness"
    
    PrompterClass = getattr(target_module, class_name)
    SYSTEM_PROMPT = getattr(target_module, "SYSTEM_PROMPT")
    
    prompter = PrompterClass()

    # 3. Generate prompts
    logging.info("Generating prompts...")
    prompts_list = df[prompt_col].tolist()
    categories_list = df[category_col].tolist() if category_col in df.columns else ['A'] * len(df) # Default category A if not present
    
    if mode == 'prompt':
        user_prompts = prompter.generate_promptchunks(prompts_list, categories_list)
    else: # response mode
        if response_col not in df.columns:
            raise ValueError(f"Response column '{response_col}' not found in input CSV.")
        responses_list = df[response_col].tolist()
        user_prompts = prompter.generate_promptchunks(prompts_list, responses_list, categories_list)

    # 4. Initialize Judge model
    logging.info(f"Initializing Judge Model: {model}")
    judge_model = CustomJudge(model=model, api_key=api_key)

    # 5. Run asynchronously
    logging.info(f"Starting evaluation for {len(user_prompts)} items...")
    tasks = [process_prompt(i, p, SYSTEM_PROMPT, judge_model) for i, p in enumerate(user_prompts)]
    results = await asyncio.gather(*tasks)

    # 6. Organize and save results
    # Convert results list to DataFrame
    results_df = pd.DataFrame(results)
    
    # Merge with original data
    out_df = pd.concat([df, results_df], axis=1)

    # Add columns in the style of judge_ours_rubric.py
    # If result is 'X', Unsafe(Yes), if 'O', Safe(No) -> judge column indicates Unsafe status
    out_df['judge'] = out_df['result'].apply(lambda x: 'Yes' if x == 'X' else 'No') 
    # safe_rubric indicates Safe status
    out_df['safe_rubric'] = out_df['result'].apply(lambda x: 'No' if x == 'X' else 'Yes')
    
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)
    out_df.to_csv(output_path, index=False, encoding='utf-8-sig')
    
    logging.info(f"Evaluation complete. Results saved to {output_path}")
    
    # Print simple statistics
    total = len(out_df)
    unsafe_count = len(out_df[out_df['result'] == 'X'])
    safe_count = len(out_df[out_df['result'] == 'O'])
    error_count = len(out_df[out_df['result'] == 'Error'])
    
    logging.info(f"Total: {total}, Safe(O): {safe_count}, Unsafe(X): {unsafe_count}, Error: {error_count}")


def main():
    parser = argparse.ArgumentParser(description='Refactored Judge Script for Prompt/Response Harmfulness')
    
    parser.add_argument('--input', '-i', required=True, help='Input CSV file path')
    parser.add_argument('--outdir', '-d', required=True, help='Output directory')
    parser.add_argument('--outfile', '-o', required=True, help='Output filename')
    
    parser.add_argument('--prompt_col', '-pc', default='seed', help='Column name for prompt (default: seed)')
    parser.add_argument('--response_col', '-rc', default='response', help='Column name for response (default: response)')
    parser.add_argument('--category_col', '-cc', default='category', help='Column name for category (default: category)')
    
    parser.add_argument('--mode', '-m', required=True, choices=['prompt', 'response'], help='Evaluation mode: prompt or response')
    parser.add_argument('--lang', '-l', required=True, choices=['en', 'ko'], help='Language: en or ko')
    
    parser.add_argument('--model', default='gpt-4.1', help='Judge model name (default: gpt-4.1)')
    parser.add_argument('--api_key', '-a', required=True, help='OpenAI API Key')

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
            api_key=args.api_key
        )
    )

if __name__ == '__main__':
    main()