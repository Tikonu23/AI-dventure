from pathlib import Path

from dotenv import load_dotenv

# .env lives at the repo root, not backend/ — main.py loads it too, but
# pytest never imports main.py, so tests need their own load.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
