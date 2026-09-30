"""Run the remaining pole questions of one arm with exactly the ablation driver's knobs.
usage: python run_pole_remainder.py <repo> <on|off> <dataset.json>
Mirrors scripts/tuning/run_ablation_model.py: SHIPPED dict (judge from argv) + EVAL_PAIRS/LIMIT/VERBOSE/SHARDS;
the only difference is the dataset file, which holds the not-yet-run pole rows verbatim from the release."""
import os, sys
repo, arm, data = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, repo); os.chdir(repo)
import eval_config as cfg, eval_run
SHIPPED = dict(METHOD="cyanchor", CYANCHOR_TOOL_SCOPE="node", RETRIEVAL_FUZZY=True, RETRIEVAL_VECTOR=False, RETRIEVAL_LEVENSHTEIN=True,
               CYPHER_SEMANTIC_REPAIR=True, PLAN_EXEC_ESCALATE=True, PLAN_EXEC_SELECT_JUDGE=(arm == "on"), PLAN_EXEC_VALUE_SNAP=True,
               GENERATOR_LLM="gpt-5.6-terra")
for k, v in SHIPPED.items(): setattr(cfg, k, v)
cfg.EVAL_PAIRS = [("zograscope_augmented", "pole")]; cfg.LIMIT = None; cfg.VERBOSE = False; cfg.SHARDS = 1
cfg.ZOGRASCOPE_AUGMENTED_PATH = data
print(f"REMAINDER judge={arm} data={data} knobs={SHIPPED}", flush=True)
rc = eval_run.main()
print(f"REMAINDER DONE rc={rc}", flush=True)
sys.exit(rc)
