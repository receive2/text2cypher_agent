"""The node-set rule: a gold query that returns a whole node is matched by a prediction that
selects exactly those nodes, whichever of their properties it returns (eval/node_set_match.py)."""
import json
import sys
import types
from pathlib import Path

import pytest

from eval import node_set_match as nsm

REPO = Path(__file__).resolve().parent.parent

GOLD_PLAIN = 'MATCH (x0:Crime)-[:OCCURRED_AT]-(x1:Location WHERE x1.address = "Pedestrian Subway") RETURN x0'
GOLD_TOPN = 'MATCH (x0:Person)-[:KNOWS_LW]-(x1:Person WHERE x1.surname = "Porter") RETURN x0 ORDER BY x0.age DESC LIMIT 1'


# ── which gold queries the rule covers ───────────────────────────────────────

@pytest.mark.parametrize("gold, var", [
    (GOLD_PLAIN, "x0"),
    (GOLD_TOPN, "x0"),
    ("MATCH (x0:Officer WHERE x0.name = \"Kania\")-[:INVESTIGATED_BY]-(x1:Crime) RETURN DISTINCT x0;", "x0"),
    ("MATCH (ah:AccountHolder)-[:HAS_ADDRESS]->(a:Address) WHERE a.state = 'Washington' WITH ah "
     "MATCH (ah)-[:HAS_CREDITCARD]->(cc:CreditCard) WHERE cc.latePayments > 0.0 RETURN ah", "ah"),
    ("MATCH (n) RETURN n", "n"),
    ("MATCH (n {name: 'x'}) RETURN n AS node", "n"),
])
def test_gold_queries_that_return_one_node(gold, var):
    assert nsm.gold_node_var(gold) == var


@pytest.mark.parametrize("gold", [
    "MATCH (x0:Person)-[:KNOWS]-(x1:Person) RETURN x0.name",                    # a property
    "MATCH (x0:Person) RETURN COUNT(DISTINCT x0)",                             # an aggregate
    "MATCH (x0:Person)-[:KNOWS]-(x1:Person) RETURN x0, x1",                     # two columns
    "MATCH (a:Person)-[r:KNOWS]->(b:Person) RETURN r",                          # a relationship
    "MATCH (p:Person) WITH p.name AS name RETURN name",                         # an alias of a scalar
    "MATCH (p:Person) WITH collect(p) AS people RETURN people",                 # an alias of a list
    "MATCH (a:Person) RETURN a UNION MATCH (a:Officer) RETURN a",               # one RETURN per branch
    "", None,
])
def test_gold_queries_the_rule_leaves_alone(gold):
    assert nsm.gold_node_var(gold) is None


# ── projecting a prediction onto its node variable ───────────────────────────

@pytest.mark.parametrize("pred, projected", [
    ('MATCH (c:Crime)-[:OCCURRED_AT]->(l:Location {address: "Pedestrian Subway"}) RETURN DISTINCT c.id',
     'MATCH (c:Crime)-[:OCCURRED_AT]->(l:Location {address: "Pedestrian Subway"}) RETURN DISTINCT c'),
    ("MATCH (p:Person) RETURN p.name AS name, p.surname AS surname ORDER BY name;",          # ORDER BY of a set is dropped
     "MATCH (p:Person) RETURN DISTINCT p"),
    ("MATCH (o:Officer) RETURN o", "MATCH (o:Officer) RETURN DISTINCT o"),
    ("MATCH (v:Vehicle)-[:INVOLVED_IN]->(c:Crime) RETURN c.id, c.date, c.type ORDER BY c.date DESC LIMIT 1",
     "MATCH (v:Vehicle)-[:INVOLVED_IN]->(c:Crime) RETURN c ORDER BY c.date DESC LIMIT 1"),
    ("MATCH (p:Person) RETURN DISTINCT p.name AS name, p.age AS age ORDER BY age DESC, name SKIP 1 LIMIT 3",
     "MATCH (p:Person) RETURN DISTINCT p ORDER BY p.age DESC, p.name SKIP 1 LIMIT 3"),
    ("MATCH (p:Person) RETURN p AS person ORDER BY person.age DESC LIMIT 2",
     "MATCH (p:Person) RETURN p ORDER BY p.age DESC LIMIT 2"),
    ("MATCH (p:Person) WITH p ORDER BY toInteger(p.age) DESC LIMIT 1 RETURN p.name",        # the limit sits in a WITH
     "MATCH (p:Person) WITH p ORDER BY toInteger(p.age) DESC LIMIT 1 RETURN DISTINCT p"),
    ("MATCH (p:Person {note: 'they RETURN later'}) RETURN p.name  // RETURN q.x",           # literal + comment
     "MATCH (p:Person {note: 'they RETURN later'}) RETURN DISTINCT p"),
    ("CALL { MATCH (q:Person) RETURN q } RETURN q.name", "CALL { MATCH (q:Person) RETURN q } RETURN DISTINCT q"),
])
def test_projection_onto_the_node_variable(pred, projected):
    assert nsm.project_to_node(pred) == projected


@pytest.mark.parametrize("pred", [
    "MATCH (p:Person)-[:KNOWS]->(f:Person) RETURN p.name, f.name",              # two variables
    "MATCH (p:Person) RETURN count(p)",                                         # an aggregate
    "MATCH (p:Person) RETURN p.name + ' ' + p.surname",                         # an expression
    "MATCH (p:Person) RETURN toLower(p.name)",
    "MATCH (p:Person) RETURN *",
    "MATCH (a:Person) RETURN a.name UNION MATCH (a:Officer) RETURN a.name",
    "MATCH (p:Person) SET p.seen = true RETURN p.name",                         # never run a writing query again
    "MATCH (p:Person) DETACH DELETE p",
    "", None,
])
def test_predictions_the_rule_cannot_project(pred):
    assert nsm.project_to_node(pred) is None


def test_a_keyword_inside_a_literal_is_not_a_clause():
    pred = 'MATCH (p:Person) WHERE p.note = "SET x LIMIT 3 UNION RETURN" RETURN p.name'
    assert nsm.project_to_node(pred) == 'MATCH (p:Person) WHERE p.note = "SET x LIMIT 3 UNION RETURN" RETURN DISTINCT p'


# ── the verdict ──────────────────────────────────────────────────────────────

CRIME_1 = {"id": "c1", "type": "Burglary", "date": "16/08/2017"}
CRIME_2 = {"id": "c2", "type": "Burglary", "date": "17/08/2017"}
CRIME_3 = {"id": "c3", "type": "Robbery", "date": "18/08/2017"}
PRED = 'MATCH (c:Crime)-[:OCCURRED_AT]->(l:Location {address: "Pedestrian Subway"}) RETURN DISTINCT c.type'


def _executor(rows=None, err=None):
    calls = []

    def run(cypher):
        calls.append(cypher)
        return rows, err
    return run, calls


def test_same_nodes_are_accepted_whatever_property_was_returned():
    gold_rows = [{"x0": CRIME_1}, {"x0": CRIME_2}, {"x0": CRIME_1}]              # the gold repeats a node per path
    run, calls = _executor([{"c": CRIME_2}, {"c": CRIME_1}])
    assert nsm.node_set_verdict(PRED, GOLD_PLAIN, gold_rows, run) is True
    assert calls == [nsm.project_to_node(PRED)]                                # judged on `RETURN DISTINCT c`, not on c.type


def test_other_nodes_with_the_same_property_values_are_rejected():
    # both crimes are burglaries: the returned values {Burglary} coincide, the nodes do not
    run, _ = _executor([{"c": CRIME_1}, {"c": CRIME_3}])
    assert nsm.node_set_verdict(PRED, GOLD_PLAIN, [{"x0": CRIME_1}, {"x0": CRIME_2}], run) is False
    run, _ = _executor([{"c": CRIME_1}])                                        # a subset is not the set
    assert nsm.node_set_verdict(PRED, GOLD_PLAIN, [{"x0": CRIME_1}, {"x0": CRIME_2}], run) is False


def test_the_rule_does_not_apply():
    run, calls = _executor([{"c": CRIME_1}])
    gold_rows = [{"x0": CRIME_1}]
    assert nsm.node_set_verdict(PRED, "MATCH (x0:Crime) RETURN x0.id", [{"x0.id": "c1"}], run) is None   # gold returns a property
    assert nsm.node_set_verdict("MATCH (c:Crime) RETURN count(c)", GOLD_PLAIN, gold_rows, run) is None    # nothing to project
    assert calls == []                                                          # ... and nothing was executed
    failing, _ = _executor(None, "ClientError: boom")
    assert nsm.node_set_verdict(PRED, GOLD_PLAIN, gold_rows, failing) is None   # the projected query does not run
    scalar, _ = _executor([{"c": "Burglary"}])
    assert nsm.node_set_verdict(PRED, GOLD_PLAIN, gold_rows, scalar) is None    # the variable is not a node


def test_judge_only_ever_turns_a_wrong_into_a_correct():
    gold_rows = [{"x0": CRIME_1}]
    run, calls = _executor([{"c": CRIME_1}])
    assert nsm.judge(True, PRED, GOLD_PLAIN, gold_rows, run) is True
    assert nsm.judge(None, PRED, GOLD_PLAIN, gold_rows, run) is None            # an errored record stays errored
    assert calls == []
    assert nsm.judge(False, PRED, GOLD_PLAIN, gold_rows, run) is True
    wrong, _ = _executor([{"c": CRIME_2}])
    assert nsm.judge(False, PRED, GOLD_PLAIN, gold_rows, wrong) is False
    assert nsm.judge(False, "MATCH (c:Crime) RETURN count(c)", GOLD_PLAIN, gold_rows, run) is False

    def explode(_cypher):
        raise RuntimeError("driver went away")
    assert nsm.judge(False, PRED, GOLD_PLAIN, gold_rows, explode) is False      # never an error out of a verdict


def test_stale_records_are_the_wrongs_decided_before_the_rule():
    old_wrong = {"ea": False, "gold_cypher": GOLD_PLAIN}
    assert nsm.is_stale(old_wrong)
    assert not nsm.is_stale({"ea": False, "ea_strict": False, "gold_cypher": GOLD_PLAIN})     # checked under the rule
    assert not nsm.is_stale({"ea": True, "gold_cypher": GOLD_PLAIN})                          # nothing to gain
    assert not nsm.is_stale({"ea": None, "gold_cypher": GOLD_PLAIN})                          # an error has no prediction
    assert not nsm.is_stale({"ea": False, "gold_cypher": "MATCH (x0:Crime) RETURN x0.id"})    # not a node-returning gold
    assert nsm.stale_count([old_wrong, {"ea": True, "gold_cypher": GOLD_PLAIN}, old_wrong]) == 2
    assert nsm.strict_value({"ea": True, "ea_strict": False}) is False
    assert nsm.strict_value({"ea": True}) is True


# ── the released benchmark: where the rule matters ───────────────────────────

def _gold_queries(dataset):
    rows = json.loads((REPO / "benchmarks" / f"{dataset}_augmented_v2" / "test.json").read_text(encoding="utf-8"))
    return [(r["graph"], r["gold_cypher"]) for r in rows]


def test_node_returning_gold_queries_of_the_release():
    per_graph = {}
    for dataset in ("cypherbench", "mindthequery", "zograscope"):
        for graph, gold in _gold_queries(dataset):
            if nsm.gold_node_var(gold) is not None:
                per_graph[(dataset, graph)] = per_graph.get((dataset, graph), 0) + 1
    # the numbers the scorer's docstring and the handout quote
    assert per_graph == {("zograscope", "pole"): 518, ("mindthequery", "bloom"): 5}


# ── the scorers record both verdicts ─────────────────────────────────────────

def _install_metrics_import_stubs():
    """Same stubs as tests/test_data_augmentation.py: the metrics modules import the agent."""
    if "agent" not in sys.modules:
        agent_pkg = types.ModuleType("agent")
        agent_pkg.__path__ = [str(REPO / "agent")]
        sys.modules["agent"] = agent_pkg
    if "agent.agent_helper" not in sys.modules:
        helper = types.ModuleType("agent.agent_helper")
        helper.neo4j_graph = None
        sys.modules["agent.agent_helper"] = helper
    if "ner_agent_auto" not in sys.modules:
        nau = types.ModuleType("ner_agent_auto")
        nau.ask_auto = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("ner_agent_auto.ask_auto stubbed in tests"))
        sys.modules["ner_agent_auto"] = nau


class _FakeGraph:
    def __init__(self, results):
        self.results, self.queries = results, []

    def query(self, cypher, params=None):
        self.queries.append(cypher)
        return self.results[cypher]


@pytest.mark.parametrize("module_name", ["eval.metrics_ZOGRASCOPE", "eval.metrics_MindTheQuery"])
def test_scorer_records_the_value_verdict_and_the_final_one(module_name, monkeypatch):
    _install_metrics_import_stubs()
    import importlib
    mod = importlib.import_module(module_name)
    graph = _FakeGraph({GOLD_PLAIN: [{"x0": CRIME_1}, {"x0": CRIME_2}],
                        nsm.project_to_node(PRED): [{"c": CRIME_1}, {"c": CRIME_2}]})
    monkeypatch.setattr(mod, "neo4j_graph", graph)
    monkeypatch.setattr(mod, "ask_auto", lambda prompt: {"cypher": PRED, "context": [{"c.type": "Burglary"}]})
    psjs_saw = {}
    monkeypatch.setattr(mod, "_compute_psjs", lambda pred, gold, neo4j_graph, ea_value: psjs_saw.setdefault("ea", ea_value) and 1.0)
    rec = mod.evaluate_one({"qid": "q1", "question": "Which crimes ...?", "cypher": GOLD_PLAIN, "graph": "pole"})
    assert rec["ea_strict"] is False and rec["ea"] is True and rec["error"] is None
    assert psjs_saw["ea"] is True                                               # PSJS falls back on the final verdict

    # a prediction that selects other nodes stays wrong under both
    graph.results[nsm.project_to_node(PRED)] = [{"c": CRIME_3}]
    rec = mod.evaluate_one({"qid": "q2", "question": "Which crimes ...?", "cypher": GOLD_PLAIN, "graph": "pole"})
    assert rec["ea_strict"] is False and rec["ea"] is False

    # a gold query that returns a property is judged exactly as before: no second execution
    gold_prop = "MATCH (x0:Crime) RETURN x0.id"
    graph.results[gold_prop] = [{"x0.id": "c1"}]
    graph.queries.clear()
    monkeypatch.setattr(mod, "ask_auto", lambda prompt: {"cypher": "MATCH (c:Crime) RETURN c.id", "context": [{"c.id": "c1"}]})
    rec = mod.evaluate_one({"qid": "q3", "question": "...", "cypher": gold_prop, "graph": "pole"})
    assert rec["ea_strict"] is True and rec["ea"] is True and graph.queries == [gold_prop]
