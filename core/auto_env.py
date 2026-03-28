"""
Auto-load .env for all Python scripts in this project.
This ensures VASTAI_CODING_API_URL, VASTAI_CODING_MODEL, and VASTAI_CODING_API_KEY are available in os.environ.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Find .env in project root
project_root = Path(__file__).parent.parent
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)

