import re
import time
from typing import List, Dict, Any
from dotenv import load_dotenv
load_dotenv() 
#pip install langchain
#pip install langchain-community
#!pip install neo4j
import os
#from langchain.graphs import Neo4jGraph
from langchain_community.graphs import Neo4jGraph
### Neo4j credentials:
neo4j_graph = None

def initialize_graph(database):
    graph = Neo4jGraph(
        url=os.environ["NEO4J_URI"],
        username=os.environ["NEO4J_USERNAME"],
        password=os.environ["NEO4J_PASSWORD"],
        database=database
    )
    return graph

def set_neo4j_graph(graph):
    global neo4j_graph
    neo4j_graph = graph

def get_neo4j_graph():
    global neo4j_graph
    if neo4j_graph is None:
        db = os.environ.get("NEO4J_DATABASE", "neo4j")
        neo4j_graph = initialize_graph(database=db)
    return neo4j_graph

# 1) index Neo4j 



def _ensure_fulltext_index(node_label: str, property_name: str) -> str:
    """
    Ensures a full-text index exists, WAITS for it to be online, 
    and provides detailed debug info.
    """
    # Dynamically generate the index name
    index_name = f"{node_label}_{property_name}_Index"
    #index_name = "jobTitleIndex"
    
    # Cypher query to create the index if it doesn't exist
    cypher_query = f"""
    CREATE FULLTEXT INDEX {index_name} IF NOT EXISTS
    FOR (n:{node_label}) ON EACH [n.{property_name}]
    """
    graph = get_neo4j_graph()
    try:
        graph.query(cypher_query)
    except Exception as e:
        print(f"ERROR: Failed to submit CREATE INDEX command. {e}")
        raise

    # --- START: Wait for Index to be ONLINE (with enhanced debugging) ---

    print(f"Waiting for index '{index_name}' to come online...")
    max_wait_seconds = 120
    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        try:
            # The syntax-corrected query
            result = graph.query(
                "SHOW FULLTEXT INDEXES YIELD name, state WHERE name = $index_name",
                params={"index_name": index_name}
            )
            
            # --- Enhanced Debugging Logic ---
            if not result:
                # This means the index doesn't seem to exist.
                print(f"DEBUG: Index '{index_name}' not found in 'SHOW INDEXES'. Retrying...")
            else:
                state = result[0].get('state') # Use .get() for safety
                if state == 'ONLINE':
                    print(f"Index '{index_name}' is ONLINE.")
                    return index_name  # Success!
                
                if state == 'FAILED':
                    # The index build failed.
                    print(f"ERROR: Index '{index_name}' has FAILED to build.")
                    raise RuntimeError(f"Index creation failed. State: {state}")
                    
                # Print the current state if not ONLINE or FAILED
                print(f"DEBUG: Index state is '{state}'. Waiting...")
            # --- End Enhanced Debugging Logic ---

        except Exception as e:
            # This will catch any *other* unexpected errors during the check
            print(f"ERROR: An error occurred while checking index status: {e}. Retrying...")
        
        time.sleep(2) # Wait for 2 seconds before checking again

    # If we exit the loop, it's a timeout
    raise TimeoutError(
        f"Index '{index_name}' did not come online after {max_wait_seconds} seconds. "
        f"Please check the Neo4j logs or run 'SHOW FULLTEXT INDEXES' manually."
    )
    # --- END: Wait for Index ---

def _ensure_fulltext_index_(node_label: str, property_name: str) -> str:
    """
    Ensures a full-text index exists for the given node label and property,
    WAITS for it to be online, and then returns the index name.
    """
    # Dynamically generate the index name
    index_name = f"{node_label}_{property_name}_Index"
    
    # Cypher query to create the index if it doesn't exist
    cypher_query = f"""
    CREATE FULLTEXT INDEX {index_name} IF NOT EXISTS
    FOR (n:{node_label}) ON EACH [n.{property_name}]
    """
    graph = get_neo4j_graph()
    graph.query(cypher_query)

    # --- START: Wait for Index to be ONLINE ---

    print(f"Waiting for index '{index_name}' to come online...")
    max_wait_seconds = 120  # Set a 2-minute timeout
    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        try:
            result = graph.query(
                "SHOW FULLTEXT INDEXES YIELD name, state WHERE name = $index_name",
                params={"index_name": index_name}
            )
            
            # Check if the index is found and its state is 'ONLINE'
            if result and result[0]['state'] == 'ONLINE':
                print(f"Index '{index_name}' is ONLINE.")
                return index_name  # The index is ready, return its name
                
        except Exception as e:
            # Catch potential errors if the index isn't queryable yet
            print(f"Checking index status... (Error: {e}). Retrying...")
        
        time.sleep(2) # Wait for 2 seconds before checking again

    # If the loop finishes without returning, the index failed to come online
    raise TimeoutError(
        f"Index '{index_name}' did not come online after {max_wait_seconds} seconds."
    )
    # --- END: Wait for Index ---

    

# 2) translate search term to Lucene fuzzy match to each token
def _lucene_query_from_phrase(phrase: str, fuzziness: int = 1) -> str:
    """
    Split the input phrase into tokens and add ~fuzziness (Lucene fuzzy matching) to each token.
    For example: "Senior Data Scientist" → "Senior~1 Data~1 Scientist~1"

    fuzziness: 0/1/2, where a larger value means looser (more tolerant) matching.
    """
    tokens = re.findall(r"[A-Za-z0-9]+", phrase)
    if not tokens:
        return f"\"{phrase}\""
    suffix = f"~{fuzziness}" if fuzziness else ""
    return " ".join(t + suffix for t in tokens)


# 3) top k similarity
def top_similar_values(
    phrase: str, 
    node_label: str, 
    property_name: str, 
    k: int = 10, 
    fuzziness: int = 1
) -> List[Dict[str, Any]]:
    """
    generate topk similarity 
    return list [{'value': 'Some Value', 'score': 12.34}, ...] 
    return list [{'title': 'Senior Data Scientist', 'score': 12.34}, ...] 
    """
    # make sure index exist
    index_name = _ensure_fulltext_index(node_label, property_name)
    
    # create Lucene search
    lucene = _lucene_query_from_phrase(phrase, fuzziness=fuzziness)

    # Dynamically build the Cypher query
    #    - node.{property_name} must be injected using an f-string
    #    - $index, $q, $k can be passed in as secure parameters
    # Deduplicate by property value: collapse nodes sharing the same value
    # and keep only the highest full-text score for each unique value.
    cypher = f"""
    CALL db.index.fulltext.queryNodes($index, $q) YIELD node, score
    WITH node.{property_name} AS value, score
    WHERE value IS NOT NULL
    RETURN value, max(score) AS score
    ORDER BY score DESC
    LIMIT $k
    """
    
    graph = get_neo4j_graph()
    rows = graph.query(
        cypher,
        params={"index": index_name, "q": lucene, "k": k}
    )
    return rows


def search_tool(
    phrase: str,
    node_label: str,
    property_name: str,
    k: int = 10,
    verbose: bool = False
) -> List[str]:
    values = []
    results = top_similar_values(
        phrase,
        node_label=node_label,
        property_name=property_name,
        k=k,
        fuzziness=1
    )
    
    for i, r in enumerate(results, 1):
        if verbose:
            print(f"{i:2d}. {r['value']}  (score={r['score']:.3f})")
        values.append(r['value']) 
    return values


#out_jobs = search_tool(phrase="Senior director", node_label="JobPosting", property_name="job_title", verbose=True)


#print(out_jobs)

#index_name = _ensure_fulltext_index(node_label = "JobPosting", property_name = "job_title")


# ──────────────────────────────────────────────────────────────────────────────
# Relationship fulltext search  (mirrors the node search_tool above)
# ──────────────────────────────────────────────────────────────────────────────

def _ensure_fulltext_rel_index(rel_type: str, property_name: str) -> str:
    """
    Create (if not exists) a fulltext index on a relationship property and
    wait up to 120 s for it to reach ONLINE state. Returns the index name.
    """
    index_name = f"{rel_type}_{property_name}_RelIndex"
    cypher_query = f"""
    CREATE FULLTEXT INDEX {index_name} IF NOT EXISTS
    FOR ()-[r:{rel_type}]-() ON EACH [r.{property_name}]
    """
    graph = get_neo4j_graph()
    try:
        graph.query(cypher_query)
    except Exception as e:
        print(f"ERROR: Failed to submit CREATE INDEX command for relationship. {e}")
        raise

    print(f"Waiting for relationship index '{index_name}' to come online...")
    max_wait_seconds = 120
    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        try:
            result = graph.query(
                "SHOW FULLTEXT INDEXES YIELD name, state WHERE name = $index_name",
                params={"index_name": index_name},
            )
            if not result:
                print(f"DEBUG: Index '{index_name}' not found yet. Retrying...")
            else:
                state = result[0].get("state")
                if state == "ONLINE":
                    print(f"Index '{index_name}' is ONLINE.")
                    return index_name
                if state == "FAILED":
                    raise RuntimeError(f"Relationship index creation failed. State: {state}")
                print(f"DEBUG: Index state is '{state}'. Waiting...")
        except Exception as e:
            print(f"ERROR: Checking relationship index status: {e}. Retrying...")
        time.sleep(2)

    raise TimeoutError(
        f"Relationship index '{index_name}' did not come online after {max_wait_seconds} s."
    )


def top_similar_rel_values(
    phrase: str,
    rel_type: str,
    property_name: str,
    k: int = 10,
    fuzziness: int = 1,
) -> List[Dict[str, Any]]:
    """
    Return the top-k matching relationship property values using fulltext search.

    Returns a list of dicts: [{'value': ..., 'score': ...}, ...]
    """
    index_name = _ensure_fulltext_rel_index(rel_type, property_name)
    lucene = _lucene_query_from_phrase(phrase, fuzziness=fuzziness)

    # Deduplicate by property value: collapse relationships sharing the same value
    # and keep only the highest full-text score for each unique value.
    cypher = f"""
    CALL db.index.fulltext.queryRelationships($index, $q) YIELD relationship, score
    WITH relationship.{property_name} AS value, score
    WHERE value IS NOT NULL
    RETURN value, max(score) AS score
    ORDER BY score DESC
    LIMIT $k
    """
    graph = get_neo4j_graph()
    rows = graph.query(cypher, params={"index": index_name, "q": lucene, "k": k})
    return rows


def search_rel_tool(
    phrase: str,
    rel_type: str,
    property_name: str,
    k: int = 10,
    verbose: bool = False,
) -> List[str]:
    """
    Search for canonical relationship property values using a fulltext index.

    Mirrors :func:`search_tool` but targets relationship properties instead of
    node properties.

    Args:
        phrase:        Search phrase extracted from the user query.
        rel_type:      Neo4j relationship type, e.g. ``"ACTED_IN"``.
        property_name: Relationship property to search, e.g. ``"roles"``.
        k:             Number of top similar values to return.
        verbose:       If True, print ranked results with scores.

    Returns:
        List of matching property values ordered by relevance score.
    """
    values = []
    results = top_similar_rel_values(
        phrase,
        rel_type=rel_type,
        property_name=property_name,
        k=k,
        fuzziness=1,
    )
    for i, r in enumerate(results, 1):
        if verbose:
            print(f"{i:2d}. {r['value']}  (score={r['score']:.3f})")
        values.append(r["value"])
    return values