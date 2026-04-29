"""
example_hf_compatible_llm.py
─────────────────────────────────────────────────────────────────────────────
End-to-end smoke test for the new ``hf_compatible`` provider.

This script shows the three ways a downstream module can build an LLM that
talks to an OpenAI-compatible endpoint (HF serverless router, HF Inference
Endpoint with TGI, Groq, Together, Fireworks, …):

  1. From a plain config dict — exactly the shape used by
     NER_LLM_CONFIG / QA_LLM_CONFIG / CYPHER_LLM_CONFIG in config.py.
  2. By calling build_llm(...) directly with provider="hf_compatible" and
     a MODEL_REGISTRY key.
  3. By overriding any of the per-stage singletons at runtime — useful for
     A/B comparisons (e.g. swap a fine-tuned model into the Cypher slot).

Run:
    python -m scripts.example_hf_compatible_llm
or:
    python scripts/example_hf_compatible_llm.py

Make sure the relevant API key (HUGGINGFACE_TOKEN, GROQ_API_KEY, …) is set
in .env before running — agent_helper loads it via python-dotenv on import.
The env-var name each registry entry expects is declared by its
``api_key_env`` field in config.MODEL_REGISTRY.
"""

from langchain_core.messages import HumanMessage

from agent.agent_helper import build_llm, build_llm_from_config


def example_1_from_config_dict() -> None:
    """Build an LLM from a config-dict, just like NER_LLM_CONFIG would."""
    cfg = {
        "provider":    "hf_compatible",
        "model":       "llama-8b-hf",       # ← key into config.MODEL_REGISTRY
        "temperature": 0,
        "max_tokens":  200,                 # forwarded to ChatOpenAI verbatim
    }
    llm = build_llm_from_config(cfg)

    resp = llm.invoke([HumanMessage(content="Say hello in one short sentence.")])
    print("[1] Llama-8B via HF router:", resp.content)


def example_2_direct_call() -> None:
    """Call build_llm() directly — same effect, different entry point."""
    llm = build_llm(
        provider="hf_compatible",
        model="llama-8b-groq",              # different registry key, different endpoint
        temperature=0,
        max_tokens=200,
    )
    resp = llm.invoke([HumanMessage(content="What is 2 + 2?")])
    print("[2] Llama-8B via Groq:", resp.content)


def example_3_swap_into_cypher_slot() -> None:
    """
    Show how to swap a fine-tuned model into the Cypher-generation slot
    without editing config.py.  Useful for evaluation runs.
    """
    from agent import agent_helper

    fine_tuned = build_llm(
        provider="hf_compatible",
        model="my-svl-cypher-lora-v1",      # registry key for your HF Inference Endpoint
        temperature=0,
    )
    # Replace the module-level singleton.  Anything that does
    # ``from agent.agent_helper import cypher_llm`` AFTER this line gets the
    # fine-tuned model; existing imports keep their reference.
    agent_helper.cypher_llm = fine_tuned
    print("[3] cypher_llm swapped to fine-tuned model:", type(fine_tuned).__name__)


if __name__ == "__main__":
    example_1_from_config_dict()
    example_2_direct_call()
    # example_3 is illustrative — uncomment after deploying the endpoint.
    # example_3_swap_into_cypher_slot()
