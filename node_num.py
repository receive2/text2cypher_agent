try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass

from neo4j import GraphDatabase
import os

# -----------------------------
# Env helpers
# -----------------------------
def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v


# -----------------------------
# Neo4j config (as requested)
# -----------------------------
neo4j_uri = _require_env("NEO4J_URI")
neo4j_user = _require_env("NEO4J_USERNAME")
neo4j_pass = _require_env("NEO4J_PASSWORD")
neo4j_db = os.getenv("NEO4J_DATABASE", "peoplekg")


def count_nodes() -> int:
    driver = GraphDatabase.driver(
        neo4j_uri,
        auth=(neo4j_user, neo4j_pass),
    )

    with driver.session(database=neo4j_db) as session:
        result = session.run(
            "MATCH (n) RETURN count(n) AS node_count"
        )
        node_count = result.single()["node_count"]

    driver.close()
    return node_count


if __name__ == "__main__":
    total_nodes = count_nodes()
    print(f"Total number of nodes in Neo4j ({neo4j_db}): {total_nodes}")
