import langchain_core
import langchain_openai
import langchain_neo4j
import openai
from importlib.metadata import version

print(f"Core: {langchain_core.__version__}")
try:
    print(f"Graph: {version('langgraph')}")
except:
    print("Graph: Not found via metadata")

print(f"OpenAI SDK: {openai.__version__}")
print("✅ All packages imported successfully!")