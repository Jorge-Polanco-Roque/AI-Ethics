"""
Statistical utilities for fairness analysis.

Mathematical Foundations
------------------------
Point estimates of fairness metrics (e.g., demographic parity difference =
0.12) are of limited value without a sense of their sampling variability.
This module provides two complementary tools:

1. **Bootstrap Confidence Intervals**

   The non-parametric bootstrap (Efron, 1979) estimates the sampling
   distribution of a statistic by repeatedly resampling the observed data
   *with replacement*.  Given B bootstrap resamples, the percentile method
   constructs a (1 - alpha) confidence interval as:

       CI = [ Q(alpha/2),  Q(1 - alpha/2) ]

   where Q(p) denotes the p-th percentile of the B bootstrap metric values.
   For example, a 95% CI uses the 2.5th and 97.5th percentiles.

   This approach is distribution-free and works for any fairness metric
   without requiring closed-form variance expressions.

2. **Risk Ratio (Disparate Impact Ratio)**

   The risk ratio (RR) is a standard epidemiological effect-size measure
   adapted for algorithmic fairness.  It compares positive-prediction rates
   between the least-favored and most-favored groups:

       RR = P(Y_hat = 1 | G = unprivileged)
            ----------------------------------
            P(Y_hat = 1 | G = privileged)

   where the privileged group is defined as the one with the highest
   positive prediction rate, and the unprivileged group as the one with the
   lowest.  The U.S. Equal Employment Opportunity Commission's "four-fifths
   rule" considers RR < 0.8 as evidence of adverse impact.

   A value of 1.0 indicates perfect parity; values below 1.0 indicate that
   the unprivileged group is under-selected relative to the privileged one.
"""

from typing import Callable, Tuple, Union

import numpy as np
import pandas as pd


def bootstrap_confidence_interval(
    metric_fn: Callable[..., float],
    y_true: Union[np.ndarray, pd.Series, list],
    y_pred: Union[np.ndarray, pd.Series, list],
    sensitive_features: Union[np.ndarray, pd.Series, list],
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    random_state: int | None = 42,
) -> Tuple[float, float]:
    """Compute a bootstrap confidence interval for a fairness metric.

    Resamples the data *with replacement* ``n_bootstrap`` times, computes
    ``metric_fn`` on each resample, and returns the percentile-based
    confidence interval.

    The percentile method is used because it is simple, assumption-free,
    and performs well when the bootstrap distribution is approximately
    symmetric -- which is typically the case for rate-based fairness
    metrics with moderate sample sizes.

    Parameters
    ----------
    metric_fn : callable
        A fairness metric function.  Its signature is auto-detected via
        ``inspect.signature``:

        - **Two-argument form**: ``metric_fn(y_pred, sensitive_features)``
          (e.g. ``demographic_parity_difference``).
        - **Three-argument form**: ``metric_fn(y_true, y_pred, sensitive_features)``
          (e.g. ``equalized_odds_difference``).

        The detection counts only required positional parameters (those
        without default values), so keyword-only or optional arguments do
        not affect the dispatch.
    y_true : array-like of shape (n_samples,)
        Ground-truth labels.  Passed to ``metric_fn`` only if the function
        accepts three positional arguments; otherwise ignored internally
        but still required for a uniform API.
    y_pred : array-like of shape (n_samples,)
        Predicted labels or values.
    sensitive_features : array-like of shape (n_samples,)
        Group membership for each sample.
    n_bootstrap : int, default 1000
        Number of bootstrap resamples.  Higher values yield more stable
        CI estimates at the cost of computation time.  1000 is a standard
        baseline; 5000-10000 is recommended for publication-quality CIs.
    confidence : float, default 0.95
        Confidence level (e.g. 0.95 for a 95% CI).
    random_state : int or None, default 42
        Seed for the random number generator, ensuring reproducibility.
        Pass ``None`` for non-deterministic behavior.

    Returns
    -------
    tuple of (float, float)
        ``(ci_lower, ci_upper)`` bounds of the confidence interval.

    Notes
    -----
    The bootstrap resampling is performed at the *observation* level: each
    resample draws n indices uniformly with replacement, and all three
    arrays (y_true, y_pred, sensitive_features) are indexed together to
    preserve the correspondence between predictions, labels, and groups.
    """
    # Flatten all inputs to 1-D numpy arrays for uniform indexing.
    y_true = np.asarray(y_true).ravel()
    y_pred = np.asarray(y_pred).ravel()
    sensitive_features = np.asarray(sensitive_features).ravel()

    n_samples = len(y_pred)

    # Use numpy's modern Generator API for reproducible random sampling.
    rng = np.random.default_rng(random_state)

    # -----------------------------------------------------------------------
    # Signature detection: determine whether metric_fn expects 2 or 3 args.
    #
    # We inspect the function's signature and count only *required*
    # positional parameters (those without default values).  This allows
    # the same bootstrap wrapper to handle both:
    #   - 2-arg metrics like demographic_parity_difference(y_pred, sf)
    #   - 3-arg metrics like equalized_odds_difference(y_true, y_pred, sf)
    # -----------------------------------------------------------------------
    import inspect

    sig = inspect.signature(metric_fn)
    n_params = sum(
        1
        for p in sig.parameters.values()
        # Only count parameters that are required (no default value) and
        # are positional (not keyword-only or **kwargs).
        if p.default is inspect.Parameter.empty
        and p.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    )
    # If the metric requires 3+ positional args, the first is y_true.
    uses_y_true = n_params >= 3

    # -----------------------------------------------------------------------
    # Bootstrap resampling loop.
    #
    # Pre-allocate the results array for performance.  On each iteration:
    #   1. Draw n_samples indices with replacement (the bootstrap sample).
    #   2. Index all arrays with the same indices to keep samples aligned.
    #   3. Evaluate the fairness metric on the resampled data.
    # -----------------------------------------------------------------------
    bootstrap_values = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        # Draw random indices with replacement; each index in [0, n_samples).
        idx = rng.integers(0, n_samples, size=n_samples)

        if uses_y_true:
            bootstrap_values[i] = metric_fn(
                y_true[idx], y_pred[idx], sensitive_features[idx]
            )
        else:
            bootstrap_values[i] = metric_fn(
                y_pred[idx], sensitive_features[idx]
            )

    # -----------------------------------------------------------------------
    # Percentile-based confidence interval.
    #
    # For a 95% CI (alpha = 0.05), we take the 2.5th and 97.5th percentiles
    # of the bootstrap distribution.  This is equivalent to trimming the
    # most extreme alpha/2 fraction from each tail.
    # -----------------------------------------------------------------------
    alpha = 1.0 - confidence
    ci_lower = float(np.percentile(bootstrap_values, 100 * alpha / 2))
    ci_upper = float(np.percentile(bootstrap_values, 100 * (1 - alpha / 2)))

    return (ci_lower, ci_upper)


def compute_effect_size(
    y_pred: Union[np.ndarray, pd.Series, list],
    sensitive_features: Union[np.ndarray, pd.Series, list],
) -> float:
    """Compute the risk ratio (disparate impact ratio) between groups.

    The risk ratio measures the relative selection rate between the least-
    and most-favored groups:

        RR = min_g P(Y_hat = 1 | G = g)
             ----------------------------
             max_g P(Y_hat = 1 | G = g)

    This formulation automatically identifies the privileged group (highest
    positive rate) and the unprivileged group (lowest positive rate) without
    requiring the caller to specify which group is which.  In a multi-group
    setting, it uses the most extreme pair, which gives the most
    conservative (worst-case) estimate of disparate impact.

    Interpretation:
    - RR = 1.0  --> perfect parity (all groups have identical selection rates)
    - RR < 1.0  --> the unprivileged group is under-selected
    - RR < 0.8  --> adverse impact under the EEOC four-fifths rule

    Parameters
    ----------
    y_pred : array-like of shape (n_samples,)
        Predicted labels (binary 0/1).
    sensitive_features : array-like of shape (n_samples,)
        Group membership for each sample.

    Returns
    -------
    float
        Risk ratio.  Returns ``float('inf')`` if the privileged group has
        a zero positive rate (division by zero), and ``1.0`` if all groups
        have zero positive rates (trivial parity).
    """
    y_pred = np.asarray(y_pred).ravel()
    sensitive_features = np.asarray(sensitive_features).ravel()

    # Compute the positive prediction rate for each group.
    # np.mean on binary labels gives the proportion of 1s, i.e.,
    # P(Y_hat = 1 | G = g).
    groups = sorted(np.unique(sensitive_features).tolist())
    rates = {
        g: float(np.mean(y_pred[sensitive_features == g])) for g in groups
    }

    max_rate = max(rates.values())
    min_rate = min(rates.values())

    # Edge case: if the highest positive rate is zero, every group has a
    # zero selection rate -- the model predicts negative for everyone,
    # which is trivially fair (no group is favored).
    if max_rate == 0.0:
        return 1.0

    # Standard risk ratio: unprivileged / privileged.
    # If max_rate > 0 but min_rate = 0, Python will return 0.0 (not inf),
    # which correctly indicates complete exclusion of the unprivileged group.
    return min_rate / max_rate
