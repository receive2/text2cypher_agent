"""
data_augmentation.datasets._common
==================================
Shared helpers for the dataset-specific augmentation scripts.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable


def ensure_clean_dir(path: Path) -> None:
    """Create *path* fresh, wiping any pre-existing contents."""
    if path.exists():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    path.mkdir(parents=True, exist_ok=True)


def copy_tree(src: Path, dst: Path) -> None:
    """Copy *src* tree into *dst*, replacing *dst* if it exists."""
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst)
    elif src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def relpath(path: Path, base: Path) -> Path:
    """Path of *path* relative to *base*."""
    return path.resolve().relative_to(base.resolve())


def split_filter(name: str, splits: Iterable[str]) -> bool:
    """
    Return True if a filename like ``train.json`` / ``Complex_test.json``
    should be augmented for the given split set.

    Heuristic: presence of the substring "test" / "train" / "valid" /
    "dev" in the filename (case-insensitive).
    """
    lower = name.lower()
    return any(s in lower for s in splits)
