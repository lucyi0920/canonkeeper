"""Runtime configuration. Every model ID and limit lives here."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
SEED_DIR = BACKEND_DIR / "seed"
STATIC_DIR = BACKEND_DIR / "static"
load_dotenv(BACKEND_DIR / ".env")

# Models — pick each by the job it does.
MODEL_ORCHESTRATOR = os.getenv("CK_MODEL_ORCHESTRATOR", "gemini-4-argon")   # canon builder, planner, adjudicator, memo
MODEL_SUBAGENT = os.getenv("CK_MODEL_SUBAGENT", "gemini-3.8-flash")          # parallel verification agents, parsing, citation checks
MODEL_IMAGE = os.getenv("CK_MODEL_IMAGE", "gemini-nano-banana-2.1")         # panel regeneration

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GCP_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "h2gdm-hack26icn-2632")

# Storage backends: "memory" for local dev/tests, "gcp" for Firestore + Cloud Storage.
STORE_BACKEND = os.getenv("CK_STORE", "memory")
ASSET_BUCKET = os.getenv("CK_BUCKET", f"{GCP_PROJECT}-canonkeeper-assets")

DEMO_CANON_ID = "demo"

# Limits
MAX_UPLOAD_BYTES = 6 * 1024 * 1024
MAX_PANELS = 40
MAX_CORPUS_CHARS = 3_000_000
MAX_REFERENCES = 40
REGEN_MAX_ATTEMPTS = 3
SUBAGENT_CONCURRENCY = 8
CONTEXT_WINDOW_TOKENS = 1_000_000
# Above this estimated size a corpus is built in volumes and merged by Argon.
VOLUME_TOKEN_BUDGET = 700_000

# Scoring (deterministic arithmetic; judgement is done by the models)
PENALTY_CRITICAL = 25
PENALTY_WARNING = 10
