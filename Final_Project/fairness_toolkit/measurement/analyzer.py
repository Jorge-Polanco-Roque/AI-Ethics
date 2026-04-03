"""
FairnessAnalyzer — Central Orchestrator of the Measurement Module.
==================================================================

This class is the primary interface for fairness evaluation in the toolkit.
It combines four capabilities into a single, easy-to-use API:

    1. Metric computation — DPD, EOD, and regression MAE disparity
    2. Bootstrap confidence intervals — statistical rigor for small samples
    3. Effect size estimation — risk ratios (disparate impact ratios)
    4. Human-readable reporting — plain-text reports with interpretive labels

The analyzer uses a registry pattern to map metric names (strings) to
callable functions, allowing the orchestrator (run_pipeline.py) to specify
metrics by name in config.yml.

Design rationale:
    - The analyzer does NOT know whether it's evaluating a baseline or a
      fair model. This is intentional — the same measurement logic is used
      in Step 1 (baseline) and Step 3 (validation) of the pipeline.
    - All results include CIs because point estimates alone are misleading
      in fairness contexts where group sample sizes can be small.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

from fairness_toolkit.measurement.metrics import (
    demographic_parity_difference,
    equalized_odds_difference,
    regression_fairness_mae,
)
from fairness_toolkit.measurement.statistical import (
    bootstrap_confidence_interval,
    compute_effect_size,
)


# ---------------------------------------------------------------------------
# Metric Registry
# ---------------------------------------------------------------------------
# Maps metric names (used in config.yml) to their implementing functions.
# To add a new metric: define it in metrics.py, then register it here.
_METRIC_REGISTRY: dict[str, callable] = {
    "demographic_parity_difference": demographic_parity_difference,
    "equalized_odds_difference": equalized_odds_difference,
    "regression_fairness_mae": regression_fairness_mae,
}

# Default metrics computed when no explicit list is provided.
_DEFAULT_METRICS = [
    "demographic_parity_difference",
    "equalized_odds_difference",
]


class FairnessAnalyzer:
    """Comprehensive fairness analysis for a single model evaluation.

    Parameters
    ----------
    y_true : array-like of shape (n_samples,)
        Ground-truth labels (binary 0/1 for classification).
    y_pred : array-like of shape (n_samples,)
        Model predictions (binary 0/1 or continuous for regression).
    sensitive_features : array-like of shape (n_samples,)
        Protected-attribute values for each sample (e.g., 'male'/'female').
    min_group_size : int, default 30
        Minimum samples per group for intersectional analysis. Groups below
        this threshold are excluded to avoid unreliable metric estimates.

    Examples
    --------
    >>> analyzer = FairnessAnalyzer(y_true, y_pred, sensitive_features)
    >>> results = analyzer.compute_metrics()
    >>> print(analyzer.generate_report())
    """

    def __init__(
        self,
        y_true: Union[np.ndarray, pd.Series, list],
        y_pred: Union[np.ndarray, pd.Series, list],
        sensitive_features: Union[np.ndarray, pd.Series, list],
        min_group_size: int = 30,
    ) -> None:
        # Flatten all inputs to 1-D numpy arrays for consistent processing
        self.y_true = np.asarray(y_true).ravel()
        self.y_pred = np.asarray(y_pred).ravel()
        self.sensitive_features = np.asarray(sensitive_features).ravel()
        self.min_group_size = min_group_size

        # Validate that all arrays have matching lengths
        if not (
            len(self.y_true) == len(self.y_pred) == len(self.sensitive_features)
        ):
            raise ValueError(
                "y_true, y_pred, and sensitive_features must all have the "
                "same number of samples."
            )

        # Pre-compute group sizes (used in reports and intersectional analysis)
        self._group_sizes: dict[str, int] = {}
        for g in sorted(np.unique(self.sensitive_features).tolist()):
            self._group_sizes[str(g)] = int(
                np.sum(self.sensitive_features == g)
            )

        # Cache for latest results — used by generate_report()
        self._last_results: Optional[dict] = None

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def compute_metrics(
        self,
        metrics: Optional[List[str]] = None,
        n_bootstrap: int = 1000,
        confidence: float = 0.95,
    ) -> Dict[str, dict]:
        """Compute fairness metrics with confidence intervals and effect sizes.

        For each requested metric, this method computes:
            - Point estimate (the metric value itself)
            - Bootstrap 95% CI (percentile-based, n_bootstrap resamples)
            - Effect size (risk ratio / disparate impact ratio)
            - Group sizes (for transparency)

        Parameters
        ----------
        metrics : list of str or None
            Metric names from the registry. Defaults to DPD + EOD.
        n_bootstrap : int, default 1000
            Number of bootstrap resamples for confidence intervals.
        confidence : float, default 0.95
            Confidence level for bootstrap CIs.

        Returns
        -------
        dict
            Nested dictionary: metric_name -> {value, ci_lower, ci_upper,
            effect_size, group_sizes}.
        """
        if metrics is None:
            metrics = list(_DEFAULT_METRICS)

        results: dict[str, dict] = {}

        for name in metrics:
            # Validate that the requested metric exists in the registry
            if name not in _METRIC_REGISTRY:
                raise ValueError(
                    f"Unknown metric '{name}'. "
                    f"Available: {list(_METRIC_REGISTRY.keys())}"
                )

            metric_fn = _METRIC_REGISTRY[name]

            # --- Detect metric signature ---
            # Some metrics take 2 args (y_pred, sensitive) like DPD,
            # others take 3 args (y_true, y_pred, sensitive) like EOD.
            # We use introspection to call them correctly.
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

            # Compute the point estimate based on the metric's arity
            if n_params >= 3:
                value = metric_fn(
                    self.y_true, self.y_pred, self.sensitive_features
                )
            else:
                value = metric_fn(self.y_pred, self.sensitive_features)

            # Compute bootstrap confidence interval
            ci_lower, ci_upper = bootstrap_confidence_interval(
                metric_fn,
                self.y_true,
                self.y_pred,
                self.sensitive_features,
                n_bootstrap=n_bootstrap,
                confidence=confidence,
            )

            # Compute effect size (risk ratio between most/least advantaged groups)
            effect = compute_effect_size(self.y_pred, self.sensitive_features)

            results[name] = {
                "value": float(value),
                "ci_lower": float(ci_lower),
                "ci_upper": float(ci_upper),
                "effect_size": float(effect),
                "group_sizes": dict(self._group_sizes),
            }

        # Cache results for use in generate_report()
        self._last_results = results
        return results

    # ------------------------------------------------------------------
    # Intersectional analysis
    # ------------------------------------------------------------------

    def compute_intersectional(
        self,
        sensitive_columns_list: List[Union[np.ndarray, pd.Series, list]],
        metrics: Optional[List[str]] = None,
        n_bootstrap: int = 500,
    ) -> Dict[str, dict]:
        """Compute fairness metrics over intersectional groups.

        Intersectional analysis examines bias at the intersection of multiple
        protected attributes (e.g., sex x age_group). This can reveal
        disparities hidden when attributes are analyzed independently.

        Groups with fewer than ``min_group_size`` samples are excluded to
        avoid unreliable estimates from tiny subgroups.

        Parameters
        ----------
        sensitive_columns_list : list of array-like
            Each element is a sensitive attribute vector. The Cartesian
            product of unique values defines intersectional groups
            (e.g., "male_young", "female_old").
        metrics : list of str or None
            Forwarded to ``compute_metrics``.
        n_bootstrap : int, default 500
            Lower default than compute_metrics for faster execution
            on the larger number of group comparisons.

        Returns
        -------
        dict
            Same structure as ``compute_metrics``, plus a special key
            ``'_excluded_groups'`` listing groups filtered by size.
        """
        arrays = [np.asarray(c).ravel() for c in sensitive_columns_list]
        n_samples = len(self.y_true)
        for arr in arrays:
            if len(arr) != n_samples:
                raise ValueError(
                    "All sensitive columns must have the same length as "
                    "y_true / y_pred."
                )

        # Build composite group labels by joining attribute values
        # e.g., ["male", "young"] -> "male_young"
        composite = np.array(
            ["_".join(str(arr[i]) for arr in arrays) for i in range(n_samples)]
        )

        # Identify groups too small for reliable analysis
        unique_groups, counts = np.unique(composite, return_counts=True)
        group_counts = dict(zip(unique_groups.tolist(), counts.tolist()))
        excluded = [
            g for g, c in group_counts.items() if c < self.min_group_size
        ]

        # Create a sub-analyzer with only the kept samples
        if excluded:
            keep_mask = np.array(
                [composite[i] not in excluded for i in range(n_samples)]
            )
            sub_analyzer = FairnessAnalyzer(
                self.y_true[keep_mask],
                self.y_pred[keep_mask],
                composite[keep_mask],
                min_group_size=self.min_group_size,
            )
        else:
            sub_analyzer = FairnessAnalyzer(
                self.y_true,
                self.y_pred,
                composite,
                min_group_size=self.min_group_size,
            )

        results = sub_analyzer.compute_metrics(
            metrics=metrics, n_bootstrap=n_bootstrap
        )
        results["_excluded_groups"] = excluded  # type: ignore[assignment]
        return results

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def generate_report(self) -> str:
        """Generate a human-readable fairness report.

        Produces a formatted plain-text report with metric values, CIs,
        effect sizes, and interpretive assessments. The interpretation
        scale follows standard thresholds from fairness literature:

            - <= 0.05: PASS (negligible disparity)
            - 0.05 - 0.10: MARGINAL (small disparity)
            - 0.10 - 0.20: WARN (moderate disparity)
            - > 0.20: FAIL (substantial disparity)

        If ``compute_metrics()`` hasn't been called yet, it is invoked
        with default settings automatically.

        Returns
        -------
        str
            Multi-line plain-text report suitable for console output.
        """
        # Auto-compute metrics if not already done
        if self._last_results is None:
            self.compute_metrics()

        assert self._last_results is not None  # for type checker

        lines: list[str] = []
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # --- Report header ---
        lines.append("=" * 64)
        lines.append("  FAIRNESS ANALYSIS REPORT")
        lines.append(f"  Generated: {timestamp}")
        lines.append("=" * 64)
        lines.append("")
        lines.append(f"  Samples:  {len(self.y_true)}")
        lines.append(f"  Groups:   {self._group_sizes}")
        lines.append("")

        # Warn about groups with insufficient sample size
        small_groups = [
            g
            for g, sz in self._group_sizes.items()
            if sz < self.min_group_size
        ]
        if small_groups:
            lines.append(
                f"  WARNING: Groups with < {self.min_group_size} samples: "
                f"{small_groups}"
            )
            lines.append("")

        # --- Per-metric results ---
        lines.append("-" * 64)
        lines.append("  METRIC RESULTS")
        lines.append("-" * 64)

        for name, data in self._last_results.items():
            if name.startswith("_"):
                continue  # Skip internal metadata like _excluded_groups

            lines.append("")
            lines.append(f"  {name}")
            lines.append(f"    Value:        {data['value']:.4f}")
            lines.append(
                f"    95% CI:       [{data['ci_lower']:.4f}, "
                f"{data['ci_upper']:.4f}]"
            )
            lines.append(f"    Effect size:  {data['effect_size']:.4f}")

            # Map the metric value to an interpretive assessment
            val = data["value"]
            if val <= 0.05:
                interpretation = "PASS -- negligible disparity"
            elif val <= 0.10:
                interpretation = "MARGINAL -- small disparity detected"
            elif val <= 0.20:
                interpretation = "WARN -- moderate disparity"
            else:
                interpretation = "FAIL -- substantial disparity"
            lines.append(f"    Assessment:   {interpretation}")

        lines.append("")
        lines.append("=" * 64)
        lines.append("  END OF REPORT")
        lines.append("=" * 64)

        return "\n".join(lines)
