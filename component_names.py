#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
component_names.py
==================
The paper's names of the five ablated CyANCHOR components, and the switches
that control them.

Every component has one switch. The **switch name** is the identifier: it is the
variable the worker reads, the key a run records in ``summary.json``
(``run_config.knobs``), what ``scripts/audit_runs.py`` compares, and it names the
ablation cells. It does not change, so runs made before the paper names existed
stay comparable with runs made after.

The **paper name** is an alias of the switch. It is accepted wherever a switch is
set:

* the ``eval_config.py`` panel, which is written with the paper names — a driver
  or a script may read or assign either name, both are one attribute;
* the environment of the standalone CLI (``config.py`` reads either variable);
* ``--variants`` of ``scripts/tuning/run_ablation_model.py`` (cell aliases).

Setting a switch and its alias to different values is always an error: nothing
here guesses which of the two was meant.
"""
from __future__ import annotations

import os
import sys
import types
from typing import Any, Dict, Mapping, MutableMapping, Tuple

# switch -> (alias accepted for it, name printed in the paper and in the reports)
COMPONENTS: Dict[str, Tuple[str, str]] = {
    "PLAN_EXEC_ESCALATE":     ("ADAPTIVE_SEARCH_CONTROL",   "Adaptive Search Control"),
    "RETRIEVAL_FUZZY":        ("TOKEN_LEVEL_FUZZY_MATCH",   "Token Level Fuzzy Match"),
    "RETRIEVAL_LEVENSHTEIN":  ("LEVENSHTEIN_RETRIEVAL",     "Levenshtein Retrieval"),
    "CYPHER_SEMANTIC_REPAIR": ("RESULT_AWARE_QUERY_REPAIR", "Result Aware Query Repair"),
    "PLAN_EXEC_VALUE_SNAP":   ("VALUE_EXISTENCE_GUARD",     "Value Existence Guard"),
}
ALIAS_OF:   Dict[str, str] = {switch: alias for switch, (alias, _) in COMPONENTS.items()}
SWITCH_OF:  Dict[str, str] = {alias: switch for switch, alias in ALIAS_OF.items()}
PAPER_NAME: Dict[str, str] = {switch: name for switch, (_, name) in COMPONENTS.items()}
_TWIN: Dict[str, str] = {**ALIAS_OF, **SWITCH_OF}          # either name -> the other

# Ablation cell (directory name under logs/ablation_*/, the cell removes one component)
# -> alias accepted by run_ablation_model.py --variants. fuzzy_only / lev_only are named
# after the retrieval arm that stays on; their aliases name the component that is removed.
CELL_ALIAS: Dict[str, str] = {
    "no_escalate":        "no_adaptive_search_control",
    "lev_only":           "no_token_level_fuzzy_match",
    "fuzzy_only":         "no_levenshtein_retrieval",
    "no_semantic_repair": "no_result_aware_query_repair",
    "no_value_snap":      "no_value_existence_guard",
}
_CELL_OF: Dict[str, str] = {alias: cell for cell, alias in CELL_ALIAS.items()}

_TRUE = ("1", "true", "yes")


def switch_name(name: str) -> str:
    """The switch *name* stands for: the switch itself, or the one its alias names."""
    return SWITCH_OF.get(name, name)


def cell_name(variant: str) -> str:
    """The ablation cell a ``--variants`` entry names: the cell itself, or the one its alias names."""
    return _CELL_OF.get(variant, variant)


def _truth(value: Any) -> bool:
    """A flag's value as config.py reads one from the environment."""
    return value.lower() in _TRUE if isinstance(value, str) else bool(value)


# ── environment (standalone CLI, and what eval_run hands to the worker) ───────

def env_flag(switch: str, default: str, env: Mapping[str, str] = os.environ) -> bool:
    """The boolean *switch* as set in the environment — under its own name or under
    its alias — else *default*. Same truth values as every other flag in config.py."""
    alias = ALIAS_OF.get(switch)
    found = {n: _truth(env[n]) for n in (switch, alias) if n and n in env}
    if len(set(found.values())) > 1:
        raise ValueError(
            f"the environment sets {switch}={env[switch]!r} and its alias {alias}={env[alias]!r}: "
            "they are two names of one switch — unset one of them.")
    return next(iter(found.values())) if found else _truth(default)


def normalize_env(env: MutableMapping[str, str]) -> None:
    """Rename every alias-named variable of *env* to its switch, in place, so that one
    name per switch reaches the worker and the run's summary."""
    for alias, switch in SWITCH_OF.items():
        if alias not in env:
            continue
        value = env.pop(alias)
        if switch in env and _truth(env[switch]) != _truth(value):
            raise ValueError(
                f"the environment sets {switch}={env[switch]!r} and its alias {alias}={value!r}: "
                "they are two names of one switch — unset one of them.")
        env.setdefault(switch, "1" if _truth(value) else "0")


# ── the eval_config panel ─────────────────────────────────────────────────────

def panel_get(panel: Any, switch: str) -> Any:
    """What *panel* (the eval_config module, or an object standing in for it) sets
    *switch* to, under the switch name or under its alias; ``None`` when neither."""
    value = getattr(panel, switch, None)
    alias = ALIAS_OF.get(switch)
    if alias is None:
        return value
    aliased = getattr(panel, alias, None)
    if value is not None and aliased is not None and bool(value) != bool(aliased):
        raise ValueError(
            f"eval_config sets {alias} = {aliased!r} and {switch} = {value!r}: "
            "they are two names of one switch — keep one.")
    return value if value is not None else aliased


class _Panel(types.ModuleType):
    """Module type of the eval_config panel: a switch and its alias are one attribute.
    The value lives under the name the panel file defines; reading or assigning the
    other name reads or assigns that same value."""

    def __getattr__(self, name: str) -> Any:               # only reached when *name* is not set
        twin = _TWIN.get(name)
        if twin is not None and twin in self.__dict__:
            return self.__dict__[twin]
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name: str, value: Any) -> None:
        twin = _TWIN.get(name)
        if twin is not None and twin in self.__dict__:
            self.__dict__.pop(name, None)
            name = twin
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        twin = _TWIN.get(name)
        if twin is not None and name not in self.__dict__ and twin in self.__dict__:
            name = twin
        super().__delattr__(name)


def unify_panel(module_name: str) -> None:
    """Called once at the end of ``eval_config.py``: from here on a switch and its alias
    are one attribute of that module. A panel file that defines both names of a switch
    (a merge leftover, an old line pasted back) is accepted when they agree and refused
    when they do not."""
    module = sys.modules.get(module_name)
    if module is None:                                      # executed outside the import system
        return
    names = module.__dict__
    for switch, alias in ALIAS_OF.items():
        if switch in names and alias in names:
            if bool(names[switch]) != bool(names[alias]):
                raise ValueError(
                    f"{module_name}.py sets {alias} = {names[alias]!r} and {switch} = {names[switch]!r}: "
                    "they are two names of one switch — keep one line.")
            del names[switch]
    module.__class__ = _Panel
