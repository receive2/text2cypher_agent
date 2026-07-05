"""
walmart_llm.py
==============
Generic OpenAI-compatible LLM client for the text2cypher verification pipeline.

Configuration (via environment variables or a .env file)
---------------------------------------------------------
  OPENAI_API_KEY      required  Your OpenAI API key (or Azure key — see below).
  OPENAI_MODEL        optional  Model name (default: gpt-4o-mini).
  OPENAI_BASE_URL     optional  Override the API base URL (e.g. a local proxy).

Azure OpenAI (all four must be set to activate Azure mode)
----------------------------------------------------------
  AZURE_OPENAI_ENDPOINT    e.g. https://<resource>.openai.azure.com/
  AZURE_OPENAI_API_KEY     Your Azure API key.
  AZURE_OPENAI_DEPLOYMENT  Deployment / model name.
  AZURE_OPENAI_API_VERSION API version string (e.g. 2024-02-01).

Usage
-----
  from scripts.walmart_llm import ask_llm
  reply = ask_llm("Summarise this in one sentence.", system="You are concise.")
"""

from __future__ import annotations

import os
from pathlib import Path

from openai import AzureOpenAI, OpenAI

# ── .env support (optional) ───────────────────────────────────────────────────
# If python-dotenv is installed, load a .env file from the repo root so that
# OPENAI_API_KEY etc. can be set there instead of in the shell environment.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # python-dotenv not installed — use shell environment only

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ── Client factory ────────────────────────────────────────────────────────────

def _make_client() -> OpenAI:
    """Return an Azure or standard OpenAI client based on environment variables."""
    azure_endpoint   = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_key        = os.getenv("AZURE_OPENAI_API_KEY")
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    azure_version    = os.getenv("AZURE_OPENAI_API_VERSION")

    if all([azure_endpoint, azure_key, azure_deployment, azure_version]):
        return AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_key,
            api_version=azure_version,
        )

    api_key  = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")

    kwargs: dict = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url

    return OpenAI(**kwargs)


# ── Public API ────────────────────────────────────────────────────────────────

def ask_llm(
    prompt: str,
    system: str = "You are a helpful assistant.",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 512,
    temperature: float = 0.0,
    timeout: int = 60,
) -> str:
    """Call the configured LLM and return the assistant's reply as a string.

    Parameters
    ----------
    prompt      : User message.
    system      : System prompt (default: "You are a helpful assistant.").
    model       : Model name; falls back to OPENAI_MODEL env var or gpt-4o-mini.
    max_tokens  : Maximum tokens in the completion.
    temperature : Sampling temperature (0 = deterministic).
    timeout     : HTTP timeout in seconds.
    """
    # Azure deployments use the deployment name set in the env, not the model arg.
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    effective_model  = azure_deployment if azure_deployment else model

    client = _make_client()

    response = client.chat.completions.create(
        model=effective_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )

    return response.choices[0].message.content


if __name__ == "__main__":
    print(ask_llm("Say hello in 3 words."))
