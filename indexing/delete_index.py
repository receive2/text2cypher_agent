import os
import time
from dotenv import load_dotenv
from langchain_community.graphs import Neo4jGraph


INDEX_TO_DROP = "jobTitleIndex"


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

def drop_index(neo4j_graph: Neo4jGraph, index_name: str):
    """
    use autocommit) delete index
    """

    cypher_query = f"DROP INDEX {index_name} IF EXISTS"
    
    try:
        print(f"DEBUG: Connecting to database '{neo4j_graph._database}'...")
        print(f"DEBUG: Submitting command in autocommit: \"{cypher_query}\"")
        
        # from LangChain  graph object neo4j driver
        driver = neo4j_graph._driver 
        
        # open session autocommit 
        with driver.session(database=neo4j_graph._database) as session:
            session.run(cypher_query) 
            
        print(f"\nSUCCESS: Command executed.")
        print(f"Index '{index_name}' has been dropped (or did not exist).")

    except Exception as e:
        print(f"\nERROR: Failed to execute DROP INDEX command.")
        print(e)
        raise


if __name__ == "__main__":
    try:
        print("Connecting to Neo4j...")
        graph = initialize_graph(database=NEO4J_DATABASE)
        
        print(f"Attempting to drop index: '{INDEX_TO_DROP}'...")
        drop_index(
            neo4j_graph=graph, 
            index_name=INDEX_TO_DROP
        )
        
        print("\nOperation complete.")
        print("You can now run 'create_index_once.py' to create the new index.")

    except Exception as e:
        print(f"\n--- SCRIPT FAILED ---")
        print(f"An error occurred: {e}")