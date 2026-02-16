import os
from dotenv import load_dotenv

load_dotenv()

# Discogs API
DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
DISCOGS_USERNAME = os.getenv("DISCOGS_USERNAME", "mprdolo")
DISCOGS_USER_AGENT = "RecordSelektah/1.0 +https://github.com/mprdolo/record-selektah"
DISCOGS_RATE_LIMIT_DELAY = 1.0  # seconds between API calls

# Flask
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-fallback-key")

# Database
DATABASE_PATH = os.path.join(os.path.dirname(__file__), "data", "recordselektah.db")

# Big Board CSV
BIG_BOARD_CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "big_board.csv")
