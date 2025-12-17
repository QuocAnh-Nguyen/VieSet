# 🕋 CAGE : A Framework for Culturally Adaptive Red-Teaming Benchmark Generation

This repository contains the evaluation framework for assessing the safety of LLM prompts and responses (PER RUBRIC). It supports both **Prompt Safety Evaluation** (checking if a prompt itself is harmful) and **Response Safety Evaluation** (checking if a model's response to a prompt is harmful) using GPT-4 based judges with specific rubrics for English and Korean.

## Directory Structure

```text
.
├── data/                   # Input datasets (CSV files)
├── evaluate/               # Core evaluation logic and rubrics
│   ├── base/               # Model wrappers (e.g., OpenAI GPT)
│   ├── template/           # Safety rubrics and prompt templates
│   │   ├── en/             # English rubrics
│   │   └── ko/             # Korean rubrics
│   └── utils/              # Utility scripts (Logger, etc.)
├── logs/                   # Execution logs (automatically created)
├── run/                    # Execution scripts
│   └── safety_judge.py     # Main entry point for evaluation
└── requirements.txt        # Python dependencies
```

## 1. Installation

Follow the steps below to set up the environment.

### Create Environment

**Using Conda:**
```bash
conda create -n safebench python=3.10 -y
conda activate safebench
```

**Or using venv:**
```bash
python3.10 -m venv safebench_env
source safebench_env/bin/activate
```

### Install Packages

```bash
pip install -r requirements.txt
```

---

## 2. Usage

The main script is `run/safety_judge.py`. It evaluates datasets using the OpenAI API (use GPT-4.1 as llm safety judge).

### Arguments

| Argument | Flag | Required | Description | Default |
| :--- | :--- | :---: | :--- | :--- |
| **Input File** | `--input`, `-i` | ✅ | Path to the input CSV file. | - |
| **Output Dir** | `--outdir`, `-d` | ✅ | Directory to save results. | - |
| **Output File** | `--outfile`, `-o` | ✅ | Name of the result CSV file. | - |
| **Mode** | `--mode`, `-m` | ✅ | Evaluation mode: `prompt` or `response`. | - |
| **Language** | `--lang`, `-l` | ✅ | Language of the rubric: `en` or `ko`. | - |
| **API Key** | `--api_key`, `-a` | ✅ | Your OpenAI API Key. | - |
| **Model** | `--model` | | Judge model name. | `gpt-4.1` |
| **Prompt Col** | `--prompt_col`, `-pc` | | Column name for the prompt. | `seed` |
| **Response Col** | `--response_col`, `-rc` | | Column name for the response (only for response mode). | `response` |
| **Category Col** | `--category_col`, `-cc` | | Column name for the category. | `category` |

### Examples

#### 1. Prompt Safety Evaluation (Korean)
Evaluates whether the input prompts themselves are harmful.

```bash
python run/safety_judge.py \
    --input data/sample_data.csv \
    --outdir results \
    --outfile result_prompt_ko.csv \
    --mode prompt \
    --lang ko \
    --api_key sk-proj-... 
```

#### 2. Response Safety Evaluation (English)
Evaluates whether the model's response to a prompt is harmful.

```bash
python run/safety_judge.py \
    --input data/sample_data.csv \
    --outdir results \
    --outfile result_response_en.csv \
    --mode response \
    --lang en \
    --api_key sk-proj-... 
```

## 3. Output

The script generates a CSV file with the following additional columns:

*   `raw_output`: The raw JSON output from the judge model.
*   `result`: The raw judgment result (`O` for Safe, `X` for Unsafe).
*   `judge`: Interpreted result (`No` for Safe, `Yes` for Unsafe).
*   `safe_rubric`: Binary safety label (`Yes` for Safe, `No` for Unsafe).