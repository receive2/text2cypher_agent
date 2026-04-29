import os
import time
from typing import List, Dict, Any 
from dotenv import load_dotenv
from langchain_community.graphs import Neo4jGraph


load_dotenv() 


NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USERNAME"]
NEO4J_PASS = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = "peoplekg"

def initialize_graph(database):
    graph = Neo4jGraph(
        url=NEO4J_URI, 
        username=NEO4J_USER, 
        password=NEO4J_PASS,
        database=database
    )
    return graph


def _ensure_fulltext_index(neo4j_graph: Neo4jGraph, node_label: str, property_name: str) -> str:
    """
    Ensures a full-text index exists, WAITS for it to be online, 
    and provides detailed debug info.
    """
    index_name = f"{node_label}_{property_name}_Index"
    cypher_query = f"""
    CREATE FULLTEXT INDEX {index_name} IF NOT EXISTS
    FOR (n:{node_label}) ON EACH [n.{property_name}]
    """
    
    try:
        print(f"DEBUG: Submitting CREATE INDEX command via raw session (autocommit)...")
        driver = neo4j_graph._driver 
        with driver.session(database=neo4j_graph._database) as session:
            session.run(cypher_query)
        print(f"DEBUG: CREATE INDEX command submitted successfully.")
    except Exception as e:
        print(f"ERROR: Failed to submit CREATE INDEX command via raw session. {e}")
        raise
    
   
    print(f"Waiting for index '{index_name}' to come online...")
    max_wait_seconds = 120  # 2-minute timeout
    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        try:
            result = neo4j_graph.query(
                "SHOW FULLTEXT INDEXES YIELD name, state WHERE name = $index_name",
                params={"index_name": index_name}
            )
            
            if not result:
                print(f"DEBUG: Index '{index_name}' not visible yet. Retrying...")
            else:
                state = result[0].get('state') 
                if state == 'ONLINE':
                    print(f"\n==========================================")
                    print(f"SUCCESS: Index '{index_name}' is ONLINE.")
                    print(f"==========================================")
                    return index_name  
                
                if state == 'FAILED':
                    print(f"ERROR: Index '{index_name}' has FAILED to build.")
                    raise RuntimeError(f"Index creation failed. State: {state}")
                    
                print(f"DEBUG: Index state is '{state}'. Waiting...")

        except Exception as e:
            print(f"ERROR: An error occurred while checking index status: {e}. Retrying...")
        
        time.sleep(2) 

    raise TimeoutError(
        f"Index '{index_name}' did not come online after {max_wait_seconds} seconds. "
        f"Please check the Neo4j logs or run 'SHOW FULLTEXT INDEXES' manually."
    )


if __name__ == "__main__":
    try:
        print("Connecting to Neo4j...")
        graph = initialize_graph(database=NEO4J_DATABASE)
        
        print("Attempting to create and verify index 'JobPosting_job_title_Index'...")
        _ensure_fulltext_index(
            neo4j_graph=graph, 
            node_label="JobPosting", 
            property_name="job_title"
        )
        
        print("\nIndex is ready. You can now run your main search script.")

    except Exception as e:
        print(f"\n--- SCRIPT FAILED ---")
        print(e)