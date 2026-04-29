# neo4j_diag.py
import os, sys, hashlib
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
from neo4j import GraphDatabase

print("="*60)
print("Neo4j Connection Diagnostics")
print("="*60)

# 1) Basic Environment Info
print("Python Executable:", sys.executable)
print("Current Working Directory (CWD):", os.getcwd())

try:
    import neo4j, langchain, pkg_resources
    print("neo4j version:", neo4j.__version__)
    try:
        import langchain_neo4j
        print("langchain-neo4j version:", pkg_resources.get_distribution("langchain-neo4j").version)
    except Exception as e:
        print("langchain-neo4j not installed or not visible:", e)
    print("langchain version:", pkg_resources.get_distribution("langchain").version)
except Exception as e:
    print("Exception reading package versions:", e)

# 2) Read .env
env_path = find_dotenv()
print("Found .env path:", env_path if env_path else "Not Found")
if env_path:
    load_dotenv(env_path, override=False)
    print("Loaded .env:", env_path)

# 3) Securely output key variables (length, prefix/suffix)
def safe_show(k):
    v = os.getenv(k)
    if v is None:
        return "❌ Not Set"
    v_stripped = v.strip()
    # Simple hash helps determine if values match between environments (e.g., Jupyter vs Script)
    h = hashlib.sha256(v_stripped.encode("utf-8")).hexdigest()[:12]
    return f"len={len(v_stripped)}, sha256[:12]={h}, startswith={v_stripped[:6]!r}, endswith={v_stripped[-6:]!r}"

keys = ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE"]
for k in keys:
    print(f"{k}: {safe_show(k)}")

# 4) Direct Connection Test (try target DB first, then default neo4j)
uri = os.getenv("NEO4J_URI", "").strip()
user = os.getenv("NEO4J_USERNAME", "").strip()
pwd  = os.getenv("NEO4J_PASSWORD", "").strip()
db_env = os.getenv("NEO4J_DATABASE")  # No strip, keep original for comparison
db_try = (db_env.strip() if db_env else "peoplekg")

def try_connect(database):
    print(f"\n=== Attempting connection to database={database!r} ===")
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        with driver.session(database=database) as sess:
            ok = sess.run("RETURN 1 AS ok").single()["ok"]
            print("Basic Connectivity: ", ok)
            # List databases to confirm if 'peoplekg' exists/online
            rows = sess.run("SHOW DATABASES").data()
            names = [(r["name"], r.get("currentStatus") or r.get("status")) for r in rows]
            print("SHOW DATABASES:", names)
    finally:
        driver.close()

try:
    try_connect(db_try)
except Exception as e1:
    print("❗ Connection Failed:", repr(e1))
    # Try default 'neo4j' database to narrow down if it's a db-name/permission issue
    if db_try != "neo4j":
        try:
            try_connect("neo4j")
        except Exception as e2:
            print("❗ Connection to 'neo4j' also failed:", repr(e2))

print("\nDiagnostics complete. Please paste the output here, and I will help you interpret it.")