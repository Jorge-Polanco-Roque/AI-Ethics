"""
Integration utilities for the Measurement Module.

This module bridges the fairness measurement subsystem with external tooling
used in production ML workflows:

1. **MLflow integration** (``log_to_mlflow``):
   Persists every fairness metric, confidence-interval bound, effect size,
   and group-size parameter into an active MLflow run so that fairness
   results are versioned alongside model artifacts and accuracy metrics.

2. **Pytest-compatible fairness gate** (``assert_fairness``):
   Provides a simple assertion function that can be dropped into any pytest
   test suite or CI/CD pipeline to enforce an upper-bound threshold on a
   chosen fairness metric, failing the build when the model exceeds it.

Both utilities rely on a small internal registry (``_get_metric_fn``) that
maps human-readable metric names to their callable implementations, keeping
the public API string-based and easy to configure from YAML/CLI.
"""

from __future__ import annotations

from typing import Union

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Internal metric registry
# ---------------------------------------------------------------------------

def _get_metric_fn(name: str):
    """Resolve a fairness metric function by its string name.

    Parameters
    ----------
    name : str
        One of the registered metric names (see ``registry`` below).

    Returns
    -------
    callable
        The corresponding metric function from ``fairness_toolkit.measurement.metrics``.

    Raises
    ------
    ValueError
        If ``name`` does not match any registered metric.

    Notes
    -----
    The import is deferred (inside the function body) to avoid circular
    imports: ``metrics.py`` and ``integrations.py`` live in the same package,
    and importing at module level would create a dependency cycle if
    ``metrics`` ever imported from ``integrations``.
    """
    from fairness_toolkit.measurement.metrics import (
        demographic_parity_difference,
        equalized_odds_difference,
        regression_fairness_mae,
    )

    # String-to-callable lookup table.  This is the single source of truth
    # for which metric names are valid in ``assert_fairness`` and anywhere
    # else that resolves metrics by name.
    registry = {
        "demographic_parity_difference": demographic_parity_difference,
        "equalized_odds_difference": equalized_odds_difference,
        "regression_fairness_mae": regression_fairness_mae,
    }

    if name not in registry:
        raise ValueError(
            f"Unknown metric '{name}'. Available: {list(registry.keys())}"
        )
    return registry[name]


# ---------------------------------------------------------------------------
# MLflow integration
# ---------------------------------------------------------------------------

def log_to_mlflow(analyzer_results: dict) -> None:
    """Log fairness analysis results to the active MLflow run.

    Iterates over the output of ``FairnessAnalyzer.compute_metrics()``
    and records each metric value, confidence-interval bounds, and
    effect size as MLflow metrics.  Group sizes are logged as MLflow
    *parameters* (not metrics) because they are fixed properties of the
    evaluation dataset rather than values that vary across training steps.

    Parameters
    ----------
    analyzer_results : dict
        Dictionary returned by ``FairnessAnalyzer.compute_metrics()``.
        Keys starting with ``_`` (internal metadata such as
        ``_excluded_groups``) are skipped.  Values that are lists (e.g.,
        intersectional breakdowns) are also skipped since MLflow metrics
        are scalar.

    Raises
    ------
    ImportError
        If ``mlflow`` is not installed.
    RuntimeError
        If there is no active MLflow run.

    Examples
    --------
    >>> import mlflow
    >>> with mlflow.start_run():
    ...     log_to_mlflow(results)  # doctest: +SKIP
    """
    # --- Guard: ensure mlflow is available -----------------------------------
    try:
        import mlflow
    except ImportError as exc:
        raise ImportError(
            "mlflow is required for log_to_mlflow. "
            "Install it with: pip install mlflow"
        ) from exc

    # --- Guard: ensure there is an active run --------------------------------
    active_run = mlflow.active_run()
    if active_run is None:
        raise RuntimeError(
            "No active MLflow run. Call mlflow.start_run() first or use "
            "a `with mlflow.start_run():` context manager."
        )

    # --- Iterate over each metric entry in the results dict ------------------
    for metric_name, data in analyzer_results.items():
        # Internal metadata keys (prefixed with '_') and list-valued entries
        # (e.g., per-group breakdowns) are not scalar metrics, so skip them.
        if isinstance(data, list) or metric_name.startswith("_"):
            continue

        # All fairness metrics are namespaced under "fairness/" in MLflow
        # so they are visually grouped and easy to filter in the UI.
        prefix = f"fairness/{metric_name}"
        mlflow.log_metric(f"{prefix}/value", data["value"])
        mlflow.log_metric(f"{prefix}/ci_lower", data["ci_lower"])
        mlflow.log_metric(f"{prefix}/ci_upper", data["ci_upper"])
        mlflow.log_metric(f"{prefix}/effect_size", data["effect_size"])

        # Group sizes are logged as *params* because they describe the
        # dataset composition and do not change within a run.  MLflow
        # raises an exception if you try to set the same param key twice
        # in the same run, so we silently catch duplicates that can occur
        # when multiple metrics share the same group structure.
        for group_label, size in data.get("group_sizes", {}).items():
            try:
                mlflow.log_param(
                    f"fairness/group_size/{group_label}", size
                )
            except mlflow.exceptions.MlflowException:
                # Param already logged in a previous metric iteration;
                # safe to ignore since the value is identical.
                pass


# ---------------------------------------------------------------------------
# Pytest-compatible assertion gate
# ---------------------------------------------------------------------------

def assert_fairness(
    y_true: Union[np.ndarray, pd.Series, list],
    y_pred: Union[np.ndarray, pd.Series, list],
    sensitive_features: Union[np.ndarray, pd.Series, list],
    metric: str = "demographic_parity_difference",
    threshold: float = 0.1,
) -> None:
    """Assert that a fairness metric is within an acceptable threshold.

    Designed to be used inside pytest test cases as a fairness gate in
    CI/CD pipelines.  If the computed metric value exceeds ``threshold``,
    an ``AssertionError`` is raised with a descriptive message, which
    pytest will report as a test failure.

    Parameters
    ----------
    y_true : array-like of shape (n_samples,)
        Ground-truth labels.
    y_pred : array-like of shape (n_samples,)
        Model predictions.
    sensitive_features : array-like of shape (n_samples,)
        Protected-attribute values.
    metric : str, default ``'demographic_parity_difference'``
        Name of the fairness metric to evaluate.  Must be one of the
        names registered in ``_get_metric_fn``.
    threshold : float, default 0.1
        Maximum acceptable value for the metric.  A common industry
        default is 0.1, corresponding to a 10 percentage-point maximum
        difference between groups.

    Raises
    ------
    AssertionError
        If the metric value exceeds *threshold*.

    Examples
    --------
    >>> assert_fairness(
    ...     [1, 0, 1, 0], [1, 0, 1, 0], ['A', 'A', 'B', 'B'],
    ...     metric='demographic_parity_difference', threshold=0.1
    ... )
    """
    import inspect

    # Resolve the metric name to a callable via the internal registry.
    metric_fn = _get_metric_fn(metric)

    # Normalize all inputs to flat 1-D numpy arrays so that downstream
    # metric functions receive a consistent type regardless of whether
    # the caller passes lists, pandas Series, or numpy arrays.
    y_true = np.asarray(y_true).ravel()
    y_pred = np.asarray(y_pred).ravel()
    sensitive_features = np.asarray(sensitive_features).ravel()

    # Introspect the metric function's signature to determine how many
    # required positional arguments it expects.  This allows us to handle
    # two different metric APIs transparently:
    #   - 3-arg metrics: fn(y_true, y_pred, sensitive_features)
    #       e.g., equalized_odds_difference (needs ground truth)
    #   - 2-arg metrics: fn(y_pred, sensitive_features)
    #       e.g., demographic_parity_difference (only needs predictions)
    sig = inspect.signature(metric_fn)
    n_params = sum(
        1
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    )

    # Dispatch based on arity: pass y_true only if the metric needs it.
    if n_params >= 3:
        value = metric_fn(y_true, y_pred, sensitive_features)
    else:
        value = metric_fn(y_pred, sensitive_features)

    # The fairness gate: raise if the metric exceeds the threshold.
    if value > threshold:
        raise AssertionError(
            f"Fairness check FAILED: {metric} = {value:.4f} "
            f"exceeds threshold {threshold:.4f}."
        )
