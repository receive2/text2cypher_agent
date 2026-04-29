import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

print("=" * 40)
print("Environment Variable Loading Check Tool")
print("=" * 40)

# Print current working directory
print("Current Working Directory (CWD):", os.getcwd())

# Find .env file
env_path = find_dotenv()
print("Found .env path:", env_path if env_path else "Not found")

# Load .env
if env_path:
    load_dotenv(env_path, override=False)
    print("Loaded .env file:", env_path)
else:
    print("⚠️ .env file not found, no variables loaded")

# Print key environment variables (avoid leaking passwords, only show whether set)
keys = ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE"]
for key in keys:
    val = os.getenv(key)
    print(f"{key}: {'Set' if val else '❌ Not set'}")


"""

pip install langchain_neo4j
pip install loguru
python -m pip install -U langchain-community
"""


