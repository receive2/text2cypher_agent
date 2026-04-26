import os
import re
import json
import ast
import asyncio
import threading
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any, Union, TypedDict, Literal, List, Dict, Optional

import httpx
import requests
from dotenv import load_dotenv
from loguru import logger

from langchain_openai import ChatOpenAI, AzureChatOpenAI
from langchain_core.messages import ToolMessage, AIMessage, HumanMessage
from langchain_core.prompts import PromptTemplate
from langchain.chat_models import init_chat_model

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import AnyMessage, add_messages
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from langchain_neo4j import Neo4jGraph, GraphCypherQAChain
from neo4j import GraphDatabase

from config import NER_SP  # NOTE: update NER_SP in config.py as shown below
from neo4j_search import search_tool


# ---------- 1. Environment & global objects ----------
load_dotenv(".env", override=True)


def build_llm(temperature: float = 0) -> ChatOpenAI:
    """Build an LLM client. Prefer Azure OpenAI if env vars are set, otherwise use public OpenAI."""
    trust_env = os.getenv("TRUST_ENV", "1") != "0"

    http_client = httpx.Client(
        timeout=httpx.Timeout(60.0, connect=10.0),
        trust_env=trust_env,
    )

    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

    if azure_endpoint and azure_key and azure_deployment:
        # Preferred path: Azure OpenAI v1 via ChatOpenAI with base_url ".../openai/v1/"
        base_url = azure_endpoint.rstrip("/") + "/openai/v1/"
        try:
            return ChatOpenAI(
                model=azure_deployment,
                api_key=azure_key,
                base_url=base_url,
                temperature=temperature,
                timeout=60,
                max_retries=6,
                http_client=http_client,
            )
        except Exception:
            # Fallback: traditional AzureChatOpenAI
            return AzureChatOpenAI(
                azure_deployment=azure_deployment,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
                api_key=azure_key,
                azure_endpoint=azure_endpoint,
                temperature=temperature,
                timeout=60,
                max_retries=6,
                http_client=http_client,
            )

    # Public OpenAI
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=temperature,
        timeout=60,
        max_retries=6,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        http_client=http_client,
    )


llm = build_llm(temperature=0)


# ---------- 2. Neo4j ----------
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USERNAME"]
NEO4J_PASS = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


def initialize_graph(database):
    return Neo4jGraph(
        url=NEO4J_URI,
        username=NEO4J_USER,
        password=NEO4J_PASS,
        database=database,
    )


neo4j_graph = initialize_graph(database=NEO4J_DATABASE)


# ---------- 3. Helpers ----------
def extract_agent_response_details(agent_response, messages):
    """Collect tool calls, tool outputs, and the final AI message from an agent run."""
    tool_calls_info = []
    tool_outputs = {}

    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                tool_calls_info.append({
                    "name": call["name"],
                    "arguments": call["args"],
                    "id": call["id"],
                })
        if isinstance(msg, ToolMessage):
            tool_outputs[msg.tool_call_id] = msg.content

    for call in tool_calls_info:
        call["output"] = tool_outputs.get(call["id"], None)

    final_message = None
    for msg in messages[::-1]:
        if isinstance(msg, AIMessage) and msg.content.strip():
            final_message = msg.content.strip()
            break

    return {"tool_calls": tool_calls_info, "final_response": final_message}


def get_entity(user_query: str, topic: str) -> str:
    """Ask the LLM to pull the keyword related to `topic` out of the user query."""
    TOOL_NER_PROMPT = """ Extract the key words related to {topic} from sentence under [TEXT]. 

[TEXT]
How many software engineers in this team?
[OUTPUT]
software engineer

[TEXT]
{user_question}
[OUTPUT]
"""
    prompt_text = (
        TOOL_NER_PROMPT
        .replace("{user_question}", user_query)
        .replace("{topic}", topic)
    )
    res = llm.invoke(prompt_text)
    return res.content


# ---------- 4. Tools — loaded dynamically from generated files ----------

def _load_generated_tools() -> List[Any]:
    """
    Import all @tool functions from generated_node_tools and generated_rel_tools.
    Returns a list of BaseTool instances, or an empty list if the generated
    files don't exist yet (pre-setup).
    """
    import importlib
    import inspect
    from langchain_core.tools import BaseTool

    tools: List[Any] = []
    for mod_name in ("generated_node_tools", "generated_rel_tools"):
        try:
            mod = importlib.import_module(mod_name)
            importlib.reload(mod)
            for _name, obj in inspect.getmembers(mod):
                if isinstance(obj, BaseTool):
                    tools.append(obj)
        except ImportError:
            logger.warning(
                f"Could not import {mod_name!r}. "
                "Run `python gen_tools.py` to generate it."
            )
    return tools


# ---------- 5. Agent ----------
def create_agent(model: str = "gpt-4.1"):
    """Create a ReAct agent wired with all generated tools."""
    tools = _load_generated_tools()
    if not tools:
        raise RuntimeError(
            "No generated tools found. "
            "Run `python setup_project.py` or `python gen_tools.py` first."
        )
    agent_graph = create_react_agent(
        model=llm,
        tools=tools,
        prompt=NER_SP,
        checkpointer=False,
    )
    return agent_graph


# ---------- 6. Output parsing ----------
def _to_list(v: Any) -> List[Any]:
    """Normalize any scalar / list-ish value into a plain Python list."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, tuple) or isinstance(v, set):
        return list(v)
    return [v]


def extract_content(input_string: str) -> str:
    """
    Parse the agent's final message into a canonical JSON string of the form
        {"Label.property": [values, ...]}

    Guarantees:
      - Returns a valid JSON string (use json.loads to get a dict back).
      - Every value is wrapped in a list.
      - Returns "{}" on any failure so downstream code never crashes.
    """
    if not input_string:
        return "{}"

    text = input_string.strip()

    # Strip optional markdown code fences (```json ... ``` or ```python ... ```)
    m = re.search(r"```(?:python|json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    # Try JSON first, then Python literal (to tolerate single quotes, etc.)
    parsed: Optional[Dict[str, Any]] = None
    for loader in (json.loads, ast.literal_eval):
        try:
            obj = loader(text)
            if isinstance(obj, dict):
                parsed = obj
                break
        except Exception:
            continue

    if parsed is None:
        return "{}"

    # Normalize every value to a list, e.g. 2015 -> [2015], "Inception" -> ["Inception"]
    normalized: Dict[str, List[Any]] = {k: _to_list(v) for k, v in parsed.items()}
    return json.dumps(normalized, ensure_ascii=False)


def get_ner(prompt: str, verbose: bool = False) -> str:
    """Run the NER agent on `prompt` and return a canonical JSON string."""
    inputs = {"messages": [("user", f"{prompt}")]}
    agent_graph = create_agent()

    message = None
    for msgs in agent_graph.stream(inputs, stream_mode="values"):
        tools_messages = [m for m in msgs["messages"] if isinstance(m, ToolMessage)]
        message = msgs["messages"][-1]

        if verbose:
            if isinstance(message, tuple):
                logger.info(message)
            else:
                message.pretty_print()

            if tools_messages:
                for tool_msg in tools_messages:
                    logger.info(tool_msg.content)

    if message is None:
        return "{}"

    return extract_content(message.content)


def get_ner_dict(prompt: str, verbose: bool = False) -> Dict[str, List[Any]]:
    """Convenience wrapper: return the entity dict as a real Python dict."""
    raw = get_ner(prompt, verbose=verbose)
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


# ---------- 7. Cypher generation prompt ----------
qa_llm = llm
cypher_llm = llm

cypher_template = """Task: Generate a Cypher statement to query a Neo4j database.

Rules:
- Use ONLY relationship types, labels, and properties present in the provided schema.
- Do NOT invent properties or relationship types not in the schema.
- Return ONLY the Cypher query (no backticks, no prose, no explanation).
- Prefer parameterized filters and safe patterns; avoid destructive operations (no WRITE).

Domain hints (PeopleKG):
- Common labels may include: Associate, Badge, JobPosting, Skill, Department, Location, etc.
- Text fields like job titles or skills may need CONTAINS/STARTS WITH with case-insensitive matching.
- If the question is ambiguous, choose the simplest valid interpretation.
- If a value is provided by schema-relevant entity filters, inline it as a literal (e.g., 2015, "CA", "Data Engineer").
- DO NOT use Cypher parameters (no `$param` anywhere).
  - Inline numbers directly: 2015
  - Inline strings directly with quotes: "Inception", "CA"
  - Example (GOOD): WHERE toLower(m.title) = toLower("Inception")
  - Example (BAD):  WHERE toLower(m.title) = toLower($movie_title)

Schema:
{schema}

similar examples:
MATCH (jp:JobPosting)-[:CONTAINS_JOB]->(jc:JobCode)
WHERE jp.state = "CA"
  AND toLower(jc.job_title) CONTAINS toLower("Data Scientist")
RETURN count(jp) AS numberOfDataScientistJobPostingsInCA

Schema-relevant attribute and values:
    - note: Whenever the following relevant attribute and value pairs are provided, you MUST incorporate it in the "where" clause in your output. You should use it all the time.
    - Relevant attribute and value pairs you MUST use:
        {relevant_entities}

User question:
{question}
"""


# ---------- 8. Run ----------
if __name__ == "__main__":
    prompt = "how many movies released before 2015?"

    # Get the canonical entity JSON string, e.g. '{"Movie.released": [2015]}'
    dct = get_ner(prompt=prompt, verbose=True)
    print("dct =", repr(dct), flush=True)

    # IMPORTANT: escape braces before injecting into PromptTemplate,
    # otherwise "{" and "}" in dct will be interpreted as template placeholders.
    safe_dct = dct.replace("{", "{{").replace("}", "}}")
    cypher_template_filled = cypher_template.replace("{relevant_entities}", safe_dct)

    cypher_prompt = PromptTemplate(
        input_variables=["schema", "question"],
        template=cypher_template_filled,
    )

    # Build GraphCypherQAChain with the custom prompt
    chain = GraphCypherQAChain.from_llm(
        graph=neo4j_graph,
        llm=qa_llm,                 # Formats Cypher results into a natural-language answer
        cypher_llm=cypher_llm,      # Generates the Cypher query
        cypher_prompt=cypher_prompt,
        verbose=True,
        allow_dangerous_requests=True,
    )

    resp = chain.invoke({"query": prompt})
    print("entities:", dct)
    print("resp:", resp)