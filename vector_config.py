# -*- coding: utf-8 -*-
"""
vector_config.py
================
Hand-written tunables for the hybrid (vector + fuzzy) retrieval layer.

This file is NEVER overwritten by `gen_system_prompt.py` or
`setup_project.py`.  The single exception is the `EMBEDDABLE_PROPERTIES`
list, which `setup_project.py` may rewrite *in-place* (only that block,
preserving everything else) when the user confirms the auto-discovery
output on a fresh database.

All schema-dependent values must come from `EMBEDDABLE_PROPERTIES`.
NEVER hardcode a label or property name anywhere else in the codebase.

Switching `TOOL_RETRIEVAL_MODE` is the ablation switch for the paper.
Existing callers see zero behaviour change while it stays at "fuzzy".
"""

from __future__ import annotations

# ─── Embedding backend ───────────────────────────────────────────────────────
# "openai"                — closed-source; default; cheap and fast
# "sentence_transformers" — open-source; required for paper reproducibility
EMBEDDING_BACKEND = "openai"   # "openai" | "sentence_transformers"

EMBEDDING_MODELS = {
    "openai": {
        "model_name": "text-embedding-3-small",
        "dimensions": 1536,
    },
    "sentence_transformers": {
        "model_name": "BAAI/bge-base-en-v1.5",
        "dimensions": 768,
        "device": None,            # None = auto-detect (cuda > mps > cpu)
        "normalize": True,         # required for cosine on most BGE/E5 models
        # Asymmetric models like BGE/E5 use a query-side instruction prefix.
        # Applied ONLY in embed_query (corpus side stays bare).
        "query_instruction": "Represent this sentence for searching relevant passages: ",
    },
}

# Derived at import — other modules import these directly and do NOT
# read `EMBEDDING_MODELS` themselves.
_active = EMBEDDING_MODELS[EMBEDDING_BACKEND]
EMBEDDING_MODEL_NAME = _active["model_name"]
EMBEDDING_DIMENSIONS = _active["dimensions"]
EMBEDDING_BATCH_SIZE = 100   # rows sent per embeddings API call

# Decoupled from EMBEDDING_BATCH_SIZE on purpose: bumping the embedding
# batch to optimise throughput must NOT balloon the Neo4j write transaction
# payload. WRITE_BATCH_SIZE caps the UNWIND size on every backfill write.
# Also used as the page size for streaming distinct-value reads.
WRITE_BATCH_SIZE = 100

# Used by `null_embedding_properties` in `CALL { ... } IN TRANSACTIONS OF N ROWS`
# to keep --reset-embeddings safe on databases with millions of nodes.
RESET_TX_BATCH_SIZE = 10000

# ─── Vector index ────────────────────────────────────────────────────────────
VECTOR_INDEX_PREFIX = "vec_idx_node"   # v1: node only. v2 will add "vec_idx_rel"
VECTOR_SIMILARITY   = "cosine"

# ─── Retrieval mode (ABLATION SWITCH) ────────────────────────────────────────
# "fuzzy"  — Lucene fulltext only (legacy, default)
# "vector" — embeddings only
# "hybrid" — both, fused via HYBRID_STRATEGY below
TOOL_RETRIEVAL_MODE = "fuzzy"          # "fuzzy" | "vector" | "hybrid"

# ─── Hybrid search parameters ────────────────────────────────────────────────
HYBRID_VECTOR_TOP_K  = 20
HYBRID_FUZZY_TOP_K   = 20
HYBRID_FINAL_TOP_K   = 10
HYBRID_STRATEGY      = "rrf"           # "rrf" | "weighted"
RRF_K                = 60              # Cormack et al. 2009 default
HYBRID_VECTOR_WEIGHT = 0.5             # used only when strategy = "weighted"
HYBRID_FUZZY_WEIGHT  = 0.5

# ─── Fuzzy re-ranking (BM25 length-norm correction) ──────────────────────────
# Enables the post-retrieval re-ranker in ``neo4j_lib.neo4j_search`` that
# boosts exact / substring / fully-covered matches over short distractors
# Lucene over-rewards.  Fixes cases like "big short" ranking "Big Rig"
# above "The Big Short" and "The Blind Side" being beaten by "Blind Side".
# Set to False to restore the legacy ordering (raw BM25, no boosts).
FUZZY_RERANK_ENABLED = True

# ─── Embeddable properties (auto-discovered, user-confirmed) ─────────────────
# IMPORTANT: each entry corresponds to ONE tool / ONE vector index.
# The "entity_type" field is "node" in v1; "relationship" is reserved for v2.
#
# Populated by `setup_project.py` step 6, which rewrites THIS BLOCK ONLY
# (everything else above is preserved).
#
# DO NOT put important comments INSIDE the block below. The whole block is
# rebuilt from scratch every time `setup_project.py --rediscover` runs, so
# any inline comments will be lost. Put notes ABOVE this header instead.
# A `vector_config.py.bak` is written before each rewrite as a safety net.
EMBEDDABLE_PROPERTIES = []
DISCOVERY_MIN_AVG_LENGTH      = 4
DISCOVERY_PROPERTY_BLACKLIST  = ["id", "uuid", "url", "uri", "embedding", "vector"]

# Stage-1 hard-exclusion data types: numeric / temporal / structural.
# A property carrying any of these data_types is NEVER embeddable.
DISCOVERY_NON_TEXT_DATA_TYPES = {
    "year", "number", "integer", "float", "date", "datetime", "time",
    "boolean", "bool", "list", "array",
}

# Stage-2 explicit-text data types: name-hint match OR membership here
# is sufficient to embed UNCONDITIONALLY (no length check).
DISCOVERY_TEXT_DATA_TYPES = {
    "title", "name", "text", "description", "summary",
}
