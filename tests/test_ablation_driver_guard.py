"""The ablation driver refuses to start while an evaluation worker runs from the same checkout.

The driver is a script that parses its arguments when it is imported, so the check is loaded
from its source instead of importing the module.
"""
import ast
from pathlib import Path

DRIVER = Path(__file__).resolve().parent.parent / "scripts" / "tuning" / "run_ablation_model.py"
REPO = Path("/home/u/repo/t2c")


def _load():
    tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "in_checkout")
    ns = {"Path": Path, "REPO": REPO}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(DRIVER), "exec"), ns)
    return ns["in_checkout"]


def _lsof(cwd):
    """What `lsof -a -p <pid> -d cwd -Fn` prints for a process in *cwd*."""
    return f"p4242\nfcwd\nn{cwd}\n"


def test_worker_in_this_checkout_is_found():
    in_checkout = _load()
    assert in_checkout(_lsof("/home/u/repo/t2c"))
    assert in_checkout(_lsof("/home/u/repo/t2c/scripts/tuning"))


def test_sibling_checkout_whose_name_starts_the_same_is_not_this_checkout():
    in_checkout = _load()
    assert not in_checkout(_lsof("/home/u/repo/t2c_b"))
    assert not in_checkout(_lsof("/home/u/repo/t2c2/eval"))


def test_other_folders_and_a_process_that_has_ended():
    in_checkout = _load()
    assert not in_checkout(_lsof("/home/u/repo"))
    assert not in_checkout(_lsof("/home/u/other"))
    assert not in_checkout("")   # the process ended between pgrep and lsof
