import logging
import re
import time
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()
#pip install langchain
#pip install langchain-community
#!pip install neo4j
import os
#from langchain.graphs import Neo4jGraph
from langchain_community.graphs import Neo4jGraph

# Hybrid retrieval imports — kept lazy at the module top so importing this
# file does NOT force loading torch / sentence-transformers when the user
# stays on the legacy fuzzy path.  vector_config is cheap; embedding_helper
# defers all heavy backend work behind module-level singletons.
import vector_config as vc

# Dedicated logger for tool-call retrieval traces. Critical for paper
# error analysis. Silence with: logging.getLogger("t2c.retrieval").setLevel(WARNING)
_retrieval_logger = logging.getLogger("t2c.retrieval")
if not _retrieval_logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[t2c.retrieval] %(message)s"))
    _retrieval_logger.addHandler(_h)
    _retrieval_logger.setLevel(logging.INFO)


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

# 2) translate search term to Lucene fuzzy match to each token

# Lucene reserved characters that MUST be escaped per
# https://lucene.apache.org/core/9_0_0/queryparser/org/apache/lucene/queryparser/classic/package-summary.html
# Order matters only insofar as backslash itself is included so the regex
# substitution doesn't mis-double it. We use a character class so the regex
# itself is single-pass.
_LUCENE_SPECIALS = re.compile(r'([+\-!(){}\[\]^"~*?:\\/&|])')


def _lucene_query_from_phrase(phrase: str, fuzziness: int = 1) -> str:
    """
    Split the input phrase into tokens and add ~fuzziness (Lucene fuzzy matching)
    to each token. Example: "Senior Data Scientist" → "Senior~1 Data~1 Scientist~1"

    Tokenisation uses ``\\w`` with ``re.UNICODE`` (the default in Py3) so that:

      • Names with apostrophes/hyphens still split into meaningful word tokens,
        e.g. ``"O'Brien"`` → ``["O", "Brien"]`` (the apostrophe is a word
        boundary; both halves still get fuzzy-matched). Better than the old
        ``[A-Za-z0-9]+`` which produced the same split but discarded any
        accented Latin characters in tokens like ``"François"``.
      • Non-Latin scripts work: ``"东京"`` → ``["东京"]`` instead of ``[]``,
        so a Chinese / Japanese / Korean / Arabic database still gets
        per-token fuzzy matching. Critical for paper portability.

    Each token is also escaped against the Lucene reserved-character set so
    user input that happens to contain ``+ - && || ! ( ) { } [ ] ^ " ~ * ? : \\``
    can't blow up the parser. The escape step is a no-op for the common
    alphanumeric case.

    fuzziness: 0/1/2 — larger means looser matching. 0 disables the suffix.
    """
    tokens = re.findall(r"\w+", phrase, flags=re.UNICODE)
    if not tokens:
        # No word characters at all (e.g. pure punctuation / emoji input).
        # Fall back to a quoted literal phrase search. The phrase itself
        # still needs Lucene-special escaping so a stray backslash or quote
        # doesn't terminate the literal early.
        escaped = _LUCENE_SPECIALS.sub(r"\\\1", phrase)
        return f'"{escaped}"'
    suffix = f"~{fuzziness}" if fuzziness else ""
    return " ".join(
        _LUCENE_SPECIALS.sub(r"\\\1", t) + suffix for t in tokens
    )


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
    verbose: bool = False,
    mode: Optional[str] = None,
) -> List[str]:
    """
    Canonical-value lookup for a (node_label, property_name) pair.

    Returns a List[str] of canonical values, ordered best-first.

    Modes:
        "fuzzy"  — Lucene fulltext (legacy, default)
        "vector" — embeddings + db.index.vector.queryNodes
        "hybrid" — both, fused via vector_config.HYBRID_STRATEGY

    When `mode is None`, falls back to vector_config.TOOL_RETRIEVAL_MODE
    so existing call sites need no edits.

    Bit-identical behaviour to the legacy implementation when
    `mode == "fuzzy"` (or default when TOOL_RETRIEVAL_MODE is "fuzzy").
    Vector / hybrid paths gracefully fall back to fuzzy on any failure.
    """
    effective_mode = (mode or vc.TOOL_RETRIEVAL_MODE).lower()

    # ── Legacy fuzzy path — preserved exactly as before ───────────────────────
    if effective_mode == "fuzzy":
        results = top_similar_values(
            phrase,
            node_label=node_label,
            property_name=property_name,
            k=k,
            fuzziness=1,
        )
        values: List[str] = []
        for i, r in enumerate(results, 1):
            if verbose:
                # Symmetry with the vector/hybrid branch below — including
                # mode in every verbose line means a copy-pasted trace can
                # never be misread as the wrong score type.
                print(f"{i:2d}. {r['value']}  (score={r['score']:.3f}, mode=fuzzy)")
            values.append(r['value'])
        _log_retrieval(phrase, node_label, property_name, "fuzzy",
                       fuzzy=results, vector=None, final=values)
        return values

    # ── Vector / hybrid paths ─────────────────────────────────────────────────
    final_top_k = vc.HYBRID_FINAL_TOP_K
    fuzzy_rows: List[Dict[str, Any]] = []
    vector_rows: List[Dict[str, Any]] = []

    try:
        if effective_mode == "vector":
            vector_rows = _vector_query_node(
                phrase, node_label, property_name,
                top_k=vc.HYBRID_VECTOR_TOP_K,
            )
            merged = vector_rows[:final_top_k]

        elif effective_mode == "hybrid":
            # NOTE(v2): parallelize fuzzy and vector branches. v1 runs them
            # sequentially because (a) it keeps the control flow obvious for
            # ablation diffing and (b) the test database is small enough that
            # latency is dominated by the embedding API call, not the DB.
            fuzzy_rows = top_similar_values(
                phrase,
                node_label=node_label,
                property_name=property_name,
                k=vc.HYBRID_FUZZY_TOP_K,
                fuzziness=1,
            )
            vector_rows = _vector_query_node(
                phrase, node_label, property_name,
                top_k=vc.HYBRID_VECTOR_TOP_K,
            )
            merged = _merge_results(
                fuzzy_rows, vector_rows,
                strategy=vc.HYBRID_STRATEGY,
                final_top_k=final_top_k,
            )
        else:
            raise ValueError(f"Unknown retrieval mode: {effective_mode!r}")

    except Exception as exc:
        _retrieval_logger.warning(
            f"FALLBACK to fuzzy: mode={effective_mode!r} "
            f"label={node_label!r} prop={property_name!r} reason={exc!r}"
        )
        # Graceful fallback: do NOT crash the agent over a retrieval failure.
        return search_tool(
            phrase=phrase,
            node_label=node_label,
            property_name=property_name,
            k=k,
            verbose=verbose,
            mode="fuzzy",
        )

    # Flatten to List[str] — internal {value, score} stays internal.
    values = [r["value"] for r in merged]
    if verbose:
        # Mode suffix tells the reader the score is RRF/weighted-fused
        # (vector/hybrid) and not a raw Lucene score (fuzzy). Without
        # this the verbose format is identical across modes and an
        # ablation trace becomes ambiguous.
        for i, r in enumerate(merged, 1):
            print(
                f"{i:2d}. {r['value']}  "
                f"(score={r['score']:.3f}, mode={effective_mode})"
            )

    _log_retrieval(phrase, node_label, property_name, effective_mode,
                   fuzzy=fuzzy_rows, vector=vector_rows, final=values)
    return values


# ──────────────────────────────────────────────────────────────────────────────
# Vector + hybrid helpers
# ──────────────────────────────────────────────────────────────────────────────

def _vector_query_node(
    phrase: str,
    node_label: str,
    property_name: str,
    top_k: int,
) -> List[Dict[str, Any]]:
    """
    Run a vector index query on the (label, property) pair.

    Returns [{value, score}, ...] in the same shape as `top_similar_values`,
    so merge logic doesn't need to know which path produced which row.

    Raises on missing index / missing API key / embedding failure — the
    caller is expected to catch and fall back to fuzzy.
    """
    # Defer the import so users on the fuzzy-only path never load it.
    from embedding_helper import embed_query, index_name_for

    index_name = index_name_for(node_label, property_name)
    graph      = get_neo4j_graph()

    # Explicit existence probe BEFORE querying. Without this, a missing
    # vector index throws a generic Neo4jError that the outer fallback
    # try/except just stringifies as ``Neo4jError(...)`` — unhelpful for
    # paper-grade error analysis. Raising a self-explanatory RuntimeError
    # here gives the t2c.retrieval log a human-readable reason while
    # still allowing the caller's graceful-fallback to fuzzy.
    exists = graph.query(
        "SHOW VECTOR INDEXES YIELD name WHERE name = $n RETURN count(*) AS c",
        params={"n": index_name},
    )
    if not exists or (exists[0].get("c") or 0) == 0:
        raise RuntimeError(
            f"Vector index {index_name!r} does not exist for "
            f"({node_label}, {property_name}). Run "
            f"`python setup_project.py` to create vector indexes, or set "
            f"TOOL_RETRIEVAL_MODE='fuzzy' in vector_config.py to bypass."
        )

    vec = embed_query(phrase)

    # Dedupe by property value: many nodes can share one value, and
    # `db.index.vector.queryNodes` returns one row per node. We keep the
    # max score per distinct value, mirroring the fuzzy path's contract.
    safe_prop = property_name.replace("`", "``")
    cypher = f"""
    CALL db.index.vector.queryNodes($index, $k, $vec) YIELD node, score
    WITH node.`{safe_prop}` AS value, score
    WHERE value IS NOT NULL
    RETURN value, max(score) AS score
    ORDER BY score DESC
    LIMIT $k
    """
    rows = graph.query(cypher, params={"index": index_name, "k": top_k, "vec": vec})
    return rows or []


def _merge_results(
    fuzzy_rows: List[Dict[str, Any]],
    vector_rows: List[Dict[str, Any]],
    strategy: str,
    final_top_k: int,
) -> List[Dict[str, Any]]:
    """
    Merge fuzzy and vector candidate lists into a single ranked list.

    `strategy`:
        "rrf"      — Reciprocal Rank Fusion (rank-based, no score scaling)
        "weighted" — min-max normalize scores, then weighted sum

    Returns [{value, score}, ...] sorted descending, length <= final_top_k.
    Score is the merged score (RRF or weighted) — NOT comparable to raw
    fuzzy/vector scores; it's only ordinal.
    """
    if strategy == "rrf":
        merged = _rrf_merge(fuzzy_rows, vector_rows, k=vc.RRF_K)
    elif strategy == "weighted":
        merged = _weighted_merge(
            fuzzy_rows, vector_rows,
            wf=vc.HYBRID_FUZZY_WEIGHT,
            wv=vc.HYBRID_VECTOR_WEIGHT,
        )
    else:
        raise ValueError(f"Unknown HYBRID_STRATEGY: {strategy!r}")

    return merged[:final_top_k]


def _rrf_merge(
    fuzzy_rows: List[Dict[str, Any]],
    vector_rows: List[Dict[str, Any]],
    k: int,
) -> List[Dict[str, Any]]:
    """
    Reciprocal Rank Fusion. score = sum_over_lists 1 / (k + rank).

    Ties are broken lexicographically by ``value`` so identical-score
    runs are byte-stable across executions — relied on by the paper's
    reproducibility section.
    """
    scores: Dict[str, float] = {}
    for rank, r in enumerate(fuzzy_rows, start=1):
        v = r["value"]
        scores[v] = scores.get(v, 0.0) + 1.0 / (k + rank)
    for rank, r in enumerate(vector_rows, start=1):
        v = r["value"]
        scores[v] = scores.get(v, 0.0) + 1.0 / (k + rank)
    out = [{"value": v, "score": s} for v, s in scores.items()]
    # Primary: score DESC. Tiebreaker: value ASC (lexicographic) for
    # byte-stable output across runs / Python dict insertion orders.
    out.sort(key=lambda r: (-r["score"], str(r["value"])))
    return out


def _weighted_merge(
    fuzzy_rows: List[Dict[str, Any]],
    vector_rows: List[Dict[str, Any]],
    wf: float,
    wv: float,
) -> List[Dict[str, Any]]:
    """Min-max normalize each list independently, then weighted sum."""
    def _norm(rows: List[Dict[str, Any]]) -> Dict[str, float]:
        if not rows:
            return {}
        vals = [r["score"] for r in rows]
        lo, hi = min(vals), max(vals)
        span = hi - lo
        if span <= 0:
            return {r["value"]: 1.0 for r in rows}
        return {r["value"]: (r["score"] - lo) / span for r in rows}

    nf = _norm(fuzzy_rows)
    nv = _norm(vector_rows)
    keys = set(nf) | set(nv)
    out  = [
        {"value": k, "score": wf * nf.get(k, 0.0) + wv * nv.get(k, 0.0)}
        for k in keys
    ]
    # Primary: score DESC. Tiebreaker: value ASC — same rationale as
    # _rrf_merge; keeps weighted-strategy output reproducible.
    out.sort(key=lambda r: (-r["score"], str(r["value"])))
    return out


def _log_retrieval(
    phrase: str,
    label: str,
    prop: str,
    mode: str,
    *,
    fuzzy: Optional[List[Dict[str, Any]]],
    vector: Optional[List[Dict[str, Any]]],
    final: List[str],
) -> None:
    """Per-call structured log line for paper-grade error analysis."""
    def _top5(rows):
        if rows is None:
            return None
        return [{"value": r["value"], "score": round(float(r["score"]), 4)}
                for r in rows[:5]]

    _retrieval_logger.info(
        "query=%r label=%s prop=%s mode=%s fuzzy_top5=%s vector_top5=%s final=%s",
        phrase, label, prop, mode,
        _top5(fuzzy), _top5(vector), final,
    )


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
    mode: Optional[str] = None,   # v1: fuzzy only; reserved for v2
) -> List[str]:
    """
    Search for canonical relationship property values using a fulltext index.

    Mirrors :func:`search_tool` but targets relationship properties instead of
    node properties.

    v1 SCOPE:  Always uses fuzzy/fulltext matching, regardless of `mode` or
    `vector_config.TOOL_RETRIEVAL_MODE`.  Relationship-property vector
    retrieval is deferred to v2 (see Fact 3 in the design doc) — the
    `mode` parameter is accepted for forward compatibility and to keep
    the call signature symmetric with `search_tool`.

    Args:
        phrase:        Search phrase extracted from the user query.
        rel_type:      Neo4j relationship type, e.g. ``"ACTED_IN"``.
        property_name: Relationship property to search, e.g. ``"roles"``.
        k:             Number of top similar values to return.
        verbose:       If True, print ranked results with scores.
        mode:          Reserved for v2; ignored in v1 (always fuzzy).

    Returns:
        List of matching property values ordered by relevance score.
    """
    if mode is not None and mode.lower() != "fuzzy":
        _retrieval_logger.info(
            "search_rel_tool: ignoring mode=%r — relationship vector "
            "retrieval is deferred to v2 (always fuzzy in v1)", mode,
        )

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

    _log_retrieval(phrase, rel_type, property_name, "fuzzy",
                   fuzzy=results, vector=None, final=values)
    return values