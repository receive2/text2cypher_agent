"""
walmart_llm.py
==============
Minimal Walmart LLM Gateway client using native cryptography (no external
walmart_gpa_peopleai_core package required).

Auth format reverse-engineered from:
  walmart_gpa_peopleai_core/auth_sig/__init__.py  (v0.34.0)

String signed: f"{consumer_id}\\n{epoch_ms}\\n{key_version}\\n"
Algorithm:     RSA-PKCS1v15-SHA256, base64-encoded
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ── Config ────────────────────────────────────────────────────────────────────
CONSUMER_ID    = "2482b985-d804-4741-aceb-a063522c3186"
LLM_ENV        = "stage"
LLM_GATEWAY_URL = "https://wmtllmgateway.stage.walmart.com/wmtllmgateway/v1/openai"
DEFAULT_MODEL  = "gpt-5.4-mini"
API_VERSION    = "2025-01-01-preview"
# gpt-5.4-mini uses max_completion_tokens (not max_tokens)
_MAX_TOKENS_PARAM = "max_completion_tokens"
KEY_VERSION    = "1"

_REPO_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_KEY_PATH = _REPO_ROOT / "keys" / "genai-ingestion-llmgateway-key.pem"


# ── Auth ──────────────────────────────────────────────────────────────────────

def _load_private_key():
    with open(PRIVATE_KEY_PATH, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _generate_headers() -> dict:
    private_key = _load_private_key()
    epoch_ms = int(time.time()) * 1000
    to_sign  = f"{CONSUMER_ID}\n{epoch_ms}\n{KEY_VERSION}\n"
    sig      = private_key.sign(to_sign.encode(), padding.PKCS1v15(), hashes.SHA256())
    auth_sig = base64.b64encode(sig).decode()

    return {
        "Content-Type":              "application/json",
        "WM_CONSUMER.ID":            CONSUMER_ID,
        "WM_CONSUMER.INTIMESTAMP":   str(epoch_ms),
        "WM_SEC.AUTH_SIGNATURE":     auth_sig,
        "WM_SEC.KEY_VERSION":        KEY_VERSION,
        "WM_SVC.ENV":                LLM_ENV,
        "WM_SVC.NAME":               "WMTLLMGATEWAY",
        "WM_LLM_GW.USER_TYPE":       "NO_END_USER",
        "WM_LLM_GW.USER_NAME":       "UNKNOWN",
        "WM_LLM_GW.USER_AGENT":      "text2cypher-verifier",
        "WM_LLM_GW.USER_IP":         "UNKNOWN",
    }


# ── Public API ────────────────────────────────────────────────────────────────

def ask_llm(
    prompt: str,
    system: str = "You are a helpful assistant.",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 512,
    temperature: float = 0.0,
    timeout: int = 60,
) -> str:
    """Call the Walmart LLM Gateway and return the assistant's reply as a string."""
    headers = _generate_headers()
    payload = json.dumps({
        "model":       model,
        "task":        "chat/completions",
        "api-version": API_VERSION,
        "model-params": {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            _MAX_TOKENS_PARAM: max_tokens,
            "temperature": temperature,
        },
    })

    resp = requests.post(
        LLM_GATEWAY_URL,
        headers=headers,
        data=payload,
        verify=False,
        timeout=timeout,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"LLM gateway {resp.status_code}: {resp.text}")

    return resp.json()["choices"][0]["message"]["content"]


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    print(ask_llm("Say hello in 3 words."))
