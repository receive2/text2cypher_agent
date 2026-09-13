#!/usr/bin/env python3
"""Per-graph empty-gold rate on the v2.2 release: execute every gold query
(read-only, no LLM) and classify error / empty / non-empty. Answers whether any
untested graph is an outlier for the empty-result repair trigger."""
import json, os, sys, glob, time, concurrent.futures as cf
from collections import Counter
sys.path.insert(0, "/Users/q0w01lh/Documents/repo/t2c"); os.chdir("/Users/q0w01lh/Documents/repo/t2c")
import eval_config as cfg
from neo4j import GraphDatabase, Query

TESTED = {"flight_accident","healthcare","pole"}
def rows_for(ds):
    p=f"benchmarks/{ds}_augmented_v2/test.json"
    by=Counter(); out={}
    for r in json.load(open(p)):
        out.setdefault(r["graph"],[]).append(r["gold_cypher"])
    return out

def probe(ds, graph, golds):
    key=(ds, "bloom50" if (ds=="mindthequery" and graph=="bloom") else graph)
    conn=cfg.GRAPH_CONNS[key]
    c=Counter(); t0=time.time()
    try:
        drv=GraphDatabase.driver(conn.uri, auth=(conn.user, conn.password))
        with drv.session(database=conn.database) as s:
            for q in golds:
                try:
                    res=s.run(Query(q, timeout=60))
                    c["empty" if res.peek() is None else "nonempty"]+=1
                    res.consume()
                except Exception as e:
                    c["error"]+=1
        drv.close()
    except Exception as e:
        return (ds, graph, len(golds), None, str(e)[:80], time.time()-t0)
    return (ds, graph, len(golds), c, None, time.time()-t0)

jobs=[]
for ds in ("cypherbench","mindthequery","zograscope"):
    for graph, golds in rows_for(ds).items(): jobs.append((ds,graph,golds))
with cf.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
    results=list(ex.map(lambda j: probe(*j), jobs))
lines=["# Empty-gold rate per graph (v2.2 release, gold queries executed live, 2026-09-12)","",
       "| dataset | graph | n | gold error | gold EMPTY | empty rate | tested? |","|---|---|---|---|---|---|---|"]
for ds,g,n,c,err,dt in sorted(results, key=lambda r:(r[0],r[1])):
    if c is None: lines.append(f"| {ds} | {g} | {n} | CONN FAIL: {err} | | | |"); continue
    lines.append(f"| {ds} | {g} | {n} | {c['error']} | {c['empty']} | {100*c['empty']/n:.1f}% | {'✓' if g in TESTED else ''} |")
open("report/empty_gold_rates.md","w").write("\n".join(lines)+"\n")
print("\n".join(lines)); print("PROBE DONE")
