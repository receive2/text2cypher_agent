import os
import difflib
from typing import List, Optional, Tuple, Any, Dict

from langchain_community.graphs import Neo4jGraph
from neo4j import GraphDatabase

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass



def _require_env(key: str) -> str:
    """Read an environment variable or raise an error if missing."""
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required env var: {key}")
    return value


# ---- Neo4j env ----
NEO4J_URI = _require_env("NEO4J_URI")
NEO4J_USER = _require_env("NEO4J_USERNAME")
NEO4J_PASS = _require_env("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "peoplekg")


def initialize_graph(database: str) -> Neo4jGraph:
    """Initialize a LangChain Neo4jGraph instance."""
    return Neo4jGraph(
        url=NEO4J_URI,
        username=NEO4J_USER,
        password=NEO4J_PASS,
        database=database,
    )


def _normalize_text(s: str) -> str:
    """Normalize text for matching (lowercase + trim)."""
    return (s or "").strip().lower()


def _similarity(a: str, b: str) -> float:
    """
    Compute similarity in [0, 1].
    Uses RapidFuzz if available; otherwise falls back to difflib.
    """
    a_n = _normalize_text(a)
    b_n = _normalize_text(b)
    if not a_n or not b_n:
        return 0.0

    # Try RapidFuzz first (optional dependency)
    try:
        from rapidfuzz import fuzz  # type: ignore
        return float(fuzz.WRatio(a_n, b_n)) / 100.0
    except Exception:
        # Built-in fallback
        return difflib.SequenceMatcher(None, a_n, b_n).ratio()


def _labels_to_type(labels: Any) -> str:
    """Convert labels list to a single node type string."""
    if isinstance(labels, list) and labels:
        return ":".join(str(x) for x in labels)
    return "Unknown"


def find_closest_node_property_value(
    query_text: str,
    database: str = NEO4J_DATABASE,
    property_keys: Optional[List[str]] = None,
    prefer_apoc: bool = True,
    scan_limit: Optional[int] = None,
) -> List[str]:
    """
    Search all node property values in Neo4j and return the closest match.

    Output format (as requested):
        [node_type, node_name, node_property_value]

    Args:
        query_text: Input string to match against all node property values.
        database: Neo4j database name.
        property_keys: If provided, only search these property keys (recommended for performance).
                       If None, search all keys on each node.
        prefer_apoc: If True, try APOC-based server-side similarity first.
        scan_limit: Optional hard LIMIT for scanned property rows (fallback path).
                    Useful to avoid extremely large scans.

    Returns:
        A list with 3 elements: [node_type, node_name, node_property_value].
        Returns [] if nothing is found.
    """
    q = (query_text or "").strip()
    if not q:
        return []

    keys_param = property_keys or []
    q_norm = _normalize_text(q)

    # ---- 1) Try APOC server-side matching (fast if APOC is installed) ----
    if prefer_apoc:
        graph = initialize_graph(database)
        cypher_apoc = """
        MATCH (n)
        WITH n,
             (CASE
                WHEN size($keys) = 0 THEN keys(n)
                ELSE [k IN keys(n) WHERE k IN $keys]
              END) AS ks
        UNWIND ks AS k
        WITH n, k, n[k] AS v
        WHERE v IS NOT NULL
        WITH n, k, toString(v) AS v_str
        WHERE size(trim(v_str)) > 0
        WITH n, v_str,
             apoc.text.jaroWinklerDistance($q_norm, toLower(v_str)) AS score
        ORDER BY score DESC
        LIMIT 1
        RETURN labels(n) AS labels,
               coalesce(n.name, n.title, n.id, n.uuid, elementId(n)) AS node_name,
               v_str AS property_value,
               score AS score
        """
        try:
            rows = graph.query(cypher_apoc, params={"q_norm": q_norm, "keys": keys_param})
            if rows:
                r = rows[0]
                node_type = _labels_to_type(r.get("labels"))
                node_name = str(r.get("node_name") or "")
                prop_val = str(r.get("property_value") or "")
                return [node_type, node_name, prop_val]
        except Exception:
            # APOC not available or procedure disabled -> fallback below
            pass

    # ---- 2) Fallback: stream all properties via official driver and match in Python ----

    cypher_stream = """
MATCH (n)
WITH n,
     (CASE
        WHEN size($keys) = 0 THEN keys(n)
        ELSE [k IN keys(n) WHERE k IN $keys]
      END) AS ks
UNWIND ks AS k
WITH n, k, n[k] AS v
WHERE v IS NOT NULL
  AND valueType(v) IN ['STRING','INTEGER','FLOAT','BOOLEAN','DATE','LOCAL_DATE_TIME','DATE_TIME','LOCAL_TIME','TIME','DURATION']
RETURN labels(n) AS labels,
       coalesce(n.name, n.title, n.id, n.uuid, elementId(n)) AS node_name,
       toString(v) AS property_value
"""


    # Apply LIMIT only if requested (to avoid accidental massive scans)
    if scan_limit is not None and scan_limit > 0:
        cypher_stream += "\nLIMIT $limit"

    best_score: float = -1.0
    best_row: Optional[Tuple[str, str, str]] = None

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        with driver.session(database=database) as session:
            params: Dict[str, Any] = {"keys": keys_param}
            if scan_limit is not None and scan_limit > 0:
                params["limit"] = int(scan_limit)

            result = session.run(cypher_stream, params)

            for record in result:
                labels = record.get("labels")
                node_type = _labels_to_type(labels)
                node_name = str(record.get("node_name") or "")
                prop_val = str(record.get("property_value") or "")

                if not prop_val.strip():
                    continue

                score = _similarity(q, prop_val)
                if score > best_score:
                    best_score = score
                    best_row = (node_type, node_name, prop_val)

        return list(best_row) if best_row else []
    finally:
        driver.close()


# -------------------------
# Example usage:
# -------------------------
if __name__ == "__main__":
    # Search across ALL properties on ALL nodes (may be slow on large graphs)
    print(find_closest_node_property_value("Data Scientist"))

    # Recommended: restrict to a few keys for better performance
    #print(find_closest_node_property_value("Alice", property_keys=["name", "fullName", "alias"]))
