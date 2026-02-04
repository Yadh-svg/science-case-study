import yaml
from pathlib import Path

try:
    prompts_file = Path(__file__).parent / "prompts.yaml"
    with open(prompts_file, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    print("YAML is valid.")
    print(f"Keys found: {len(data.keys())}")
except Exception as e:
    print(f"YAML Error: {e}")
