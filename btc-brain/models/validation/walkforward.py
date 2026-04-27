"""
Chronological walk-forward validator with purging + embargo.

Splits a labeled (X, y, t_index) dataset into a sequence of (train, test)
folds such that:
  * train indices are strictly earlier than test indices,
  * a purge of `purge_bars` rows is removed from the END of each train fold
    to prevent label leakage from overlapping H-bar targets,
  * an embargo of `embargo_bars` rows is removed from the START of the next
    test fold (boundary cushion for autocorrelation).

We never random-split. We never use future data in train. The test fold
ALWAYS sits chronologically after its train fold.

Scaling
-------
`fit_scaler(X_train)` returns mean/std parameters. `apply_scaler(X, params)`
uses those parameters without refitting. This makes the train/test
separation explicit and prevents test data from leaking into the scaler.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Fold:
    fold_id: int
    train_idx: list[int]
    test_idx: list[int]
    purged: int
    embargoed: int


def walk_forward_splits(
    n_rows: int,
    n_folds: int = 5,
    purge_bars: int = 1,
    embargo_bars: int = 1,
    min_train: int = 30,
) -> list[Fold]:
    """Build sequential train/test folds.

    Strategy: expanding window. Test fold k uses the *first* (k+1) * fold_size
    rows of which the trailing fold_size are test. We then purge the last
    `purge_bars` of train and embargo the first `embargo_bars` of test.

    Returns [] if n_rows is too small for `min_train + n_folds` rows.
    """
    if n_rows <= 0 or n_folds <= 0:
        return []
    fold_size = max(1, (n_rows - min_train) // n_folds)
    if fold_size <= 0:
        return []
    folds: list[Fold] = []
    for k in range(n_folds):
        test_start = min_train + k * fold_size
        test_end = test_start + fold_size
        if test_end > n_rows:
            break
        train_end = test_start
        # Purge: drop the trailing purge_bars of train.
        train_idx = list(range(0, max(0, train_end - purge_bars)))
        # Embargo: drop the leading embargo_bars of test.
        test_idx = list(range(test_start + embargo_bars, test_end))
        # Refuse degenerate folds.
        if len(train_idx) < min_train or len(test_idx) == 0:
            continue
        folds.append(Fold(
            fold_id=k,
            train_idx=train_idx,
            test_idx=test_idx,
            purged=purge_bars,
            embargoed=embargo_bars,
        ))
    return folds


# ── Scaler (fit-on-train) ──────────────────────────────────────────────────
@dataclass
class ScalerParams:
    means: list[float]
    stds: list[float]


def fit_scaler(X: list[list[float]]) -> ScalerParams:
    if not X:
        return ScalerParams(means=[], stds=[])
    n_cols = len(X[0])
    means = [0.0] * n_cols
    for row in X:
        for j in range(n_cols):
            means[j] += row[j]
    means = [m / len(X) for m in means]
    stds = [0.0] * n_cols
    for row in X:
        for j in range(n_cols):
            stds[j] += (row[j] - means[j]) ** 2
    stds = [
        math.sqrt(s / max(1, len(X) - 1)) if len(X) > 1 else 1.0 for s in stds
    ]
    # Avoid divide-by-zero on constant columns.
    stds = [s if s > 1e-9 else 1.0 for s in stds]
    return ScalerParams(means=means, stds=stds)


def apply_scaler(X: list[list[float]], p: ScalerParams) -> list[list[float]]:
    if not X:
        return []
    out = []
    for row in X:
        out.append([(row[j] - p.means[j]) / p.stds[j] for j in range(len(row))])
    return out


def select(rows: list, idx: list[int]) -> list:
    return [rows[i] for i in idx]
