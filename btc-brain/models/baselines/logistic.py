"""
Pure-Python L2-regularized logistic regression.

Fits weights via batch gradient descent with optional L2 penalty.

API mirrors the baseline fit/predict_proba shape so the same training
harness works for everything.

This is intentionally NOT a substitute for sklearn — but it is fully
deterministic, dependency-free, and adequate for shadow-mode evaluation
of small feature vectors over O(10^3) samples.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


@dataclass
class LogisticRegression:
    """L2-regularized logistic regression via batch gradient descent."""

    lr: float = 0.1
    n_iters: int = 500
    l2: float = 0.01
    fit_intercept: bool = True
    seed: int = 7
    name: str = "logistic"

    def __post_init__(self):
        self.weights: list[float] = []
        self.intercept: float = 0.0

    def fit(self, X: list[list[float]], y: list[int], meta=None):
        if not X:
            self.weights = []
            self.intercept = 0.0
            return self
        n_samples = len(X)
        n_features = len(X[0])
        # Init weights to zero — matches sklearn `fit_intercept` default.
        w = [0.0] * n_features
        b = 0.0
        for _ in range(self.n_iters):
            grad_w = [0.0] * n_features
            grad_b = 0.0
            for i in range(n_samples):
                z = b
                row = X[i]
                for j in range(n_features):
                    z += w[j] * row[j]
                p = _sigmoid(z)
                err = p - y[i]
                grad_b += err
                for j in range(n_features):
                    grad_w[j] += err * row[j]
            grad_b /= n_samples
            for j in range(n_features):
                grad_w[j] = grad_w[j] / n_samples + self.l2 * w[j]
            # update
            if self.fit_intercept:
                b -= self.lr * grad_b
            for j in range(n_features):
                w[j] -= self.lr * grad_w[j]
        self.weights = w
        self.intercept = b if self.fit_intercept else 0.0
        return self

    def predict_proba(self, X: list[list[float]], meta=None) -> list[float]:
        out = []
        if not self.weights:
            return [0.5] * len(X)
        for row in X:
            z = self.intercept
            for j in range(len(self.weights)):
                z += self.weights[j] * row[j]
            out.append(_sigmoid(z))
        return out


# ── Optional tree-based model: tries to import xgboost/lightgbm. ───────────
def maybe_load_tree_model():
    """Return (name, ctor) for an available tree model, or (None, None).

    Tree models are *optional* per Phase 3 spec. The shadow framework still
    runs even when none is installed — we record a `skipped:dependency_missing`
    registry entry instead.
    """
    try:
        import xgboost  # noqa: F401
        return ("xgboost", "xgboost.XGBClassifier")
    except ImportError:
        pass
    try:
        import lightgbm  # noqa: F401
        return ("lightgbm", "lightgbm.LGBMClassifier")
    except ImportError:
        pass
    return (None, None)
