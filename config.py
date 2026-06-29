"""Central configuration for the Loop Engineering framework (Stage 1)."""

import os

# Ollama HTTP API host. Override with OLLAMA_HOST env var if needed.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Model roles -> Ollama model tags.
SUPERVISOR_MODEL = os.environ.get("SUPERVISOR_MODEL", "qwen3:30b")
CODER_MODEL = os.environ.get("CODER_MODEL", "qwen2.5-coder:32b")

# Generation options passed to Ollama.
REQUEST_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))  # seconds
TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0.3"))
# Per model-call wall-clock cap used by the loop engine so a stuck/slow model
# cannot hang the loop indefinitely (Stage 3.2.2).
MODEL_CALL_TIMEOUT = int(os.environ.get("LOOP_MODEL_CALL_TIMEOUT", "300"))  # seconds

# Retry loop: number of EXTRA coder/reviewer attempts after the first one.
# "Retry up to 3 times" => 3 retries, so max_attempts = MAX_RETRIES + 1 = 4.
MAX_RETRIES = int(os.environ.get("LOOP_MAX_RETRIES", "3"))

# Safe workspace directory (relative to the project root). ALL file writes are
# confined here. Path traversal outside it is rejected.
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "workspace")

# Command execution (Stage 1.3): per-command timeout and a cap on how many
# suggested commands will be executed per attempt.
COMMAND_TIMEOUT = int(os.environ.get("LOOP_COMMAND_TIMEOUT", "30"))  # seconds
MAX_COMMANDS = int(os.environ.get("LOOP_MAX_COMMANDS", "5"))

# SQLite persistence (Stage 1.4). Database file lives at the project root.
DB_FILE = os.environ.get("LOOP_DB_FILE", "loop_engineering.db")

# Default task used when none is supplied on the command line / prompt.
DEFAULT_TASK = "Write a Python function that returns the nth Fibonacci number."
