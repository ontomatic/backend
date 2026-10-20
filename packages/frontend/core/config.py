import os
from pathlib import Path

from dotenv import load_dotenv

FRONTEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(FRONTEND_ROOT / '.env')

API_URL = os.getenv('API_URL', 'http://localhost:8000')
