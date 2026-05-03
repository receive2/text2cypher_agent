"""
data_augmentation.datasets
==========================
Dataset-specific augmentation scripts.  Each module exposes a
``run(...)`` function called by the repo-root
``run_data_augmentation.py`` runner.
"""

from data_augmentation.datasets import (  # noqa: F401
    augment_cypherbench,
    augment_mindthequery,
    augment_zograscope,
)


def get_runner(dataset: str):
    """Return the ``run`` callable for *dataset*."""
    if dataset == "cypherbench":
        return augment_cypherbench.run
    if dataset == "mindthequery":
        return augment_mindthequery.run
    if dataset == "zograscope":
        return augment_zograscope.run
    raise ValueError(
        f"Unknown dataset {dataset!r}; expected one of "
        "{'cypherbench', 'mindthequery', 'zograscope'}."
    )
