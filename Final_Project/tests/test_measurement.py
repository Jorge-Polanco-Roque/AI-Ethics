"""
Unit and functional tests for the MeasurementModule.

This module validates the fairness measurement layer of the toolkit, which is
responsible for computing, analyzing, and reporting fairness metrics.  The tests
are organized in four layers:

1. **Metric unit tests** (``TestDemographicParity``, ``TestEqualizedOdds``):
   Verify that individual metric functions return correct values for trivial
   edge cases (perfect parity, maximum disparity) and for the synthetic biased
   dataset defined in ``conftest.py``.

2. **Statistical unit tests** (``TestBootstrapCI``, ``TestEffectSize``):
   Ensure that bootstrap confidence intervals are well-formed (contain the
   point estimate, have a reasonable width) and that effect-size computations
   return sensible values.

3. **Analyzer functional tests** (``TestFairnessAnalyzer``):
   Exercise the ``FairnessAnalyzer`` facade, checking that it computes metrics,
   attaches confidence intervals and effect sizes, and renders a text report.

4. **Assertion functional tests** (``TestAssertFairness``):
   Validate the pytest-compatible ``assert_fairness`` helper, confirming that
   it passes for fair data and raises ``AssertionError`` for biased data.

All tests use the ``synthetic_binary_data`` fixture from ``conftest.py`` unless
they construct their own minimal arrays to test a specific edge case.
"""

import numpy as np
import pytest

from fairness_toolkit.measurement.metrics import (
    demographic_parity_difference,
    equalized_odds_difference,
)
from fairness_toolkit.measurement.statistical import (
    bootstrap_confidence_interval,
    compute_effect_size,
)
from fairness_toolkit.measurement.analyzer import FairnessAnalyzer
from fairness_toolkit.measurement.integrations import assert_fairness


# ======================== Unit Tests: Metrics ========================

class TestDemographicParity:
    """Validate the ``demographic_parity_difference`` metric.

    Demographic Parity Difference (DPD) is defined as the absolute difference
    in positive-prediction rates between groups.  These tests cover the three
    canonical scenarios: identical rates (DPD = 0), fully separated rates
    (DPD = 1), and the controlled synthetic bias case (DPD > 0.1).
    """

    def test_perfect_parity(self):
        """When both groups have the same positive rate, DPD should be ~0."""
        # Construct symmetric data: each group has exactly 50% positive rate
        y_pred = np.array([1, 0, 1, 0, 1, 0, 1, 0])
        sensitive = np.array(["A", "A", "A", "A", "B", "B", "B", "B"])
        result = demographic_parity_difference(y_pred, sensitive)
        # Tolerance of 0.01 accounts for floating-point representation only;
        # with perfectly balanced binary arrays the result should be exactly 0.
        assert abs(result) < 0.01

    def test_maximum_disparity(self):
        """When one group is all positive and other all negative, DPD should be 1."""
        # Group A gets all 1s, Group B gets all 0s -> DPD = |1.0 - 0.0| = 1.0
        y_pred = np.array([1, 1, 1, 1, 0, 0, 0, 0])
        sensitive = np.array(["A", "A", "A", "A", "B", "B", "B", "B"])
        result = demographic_parity_difference(y_pred, sensitive)
        assert abs(result) == 1.0

    def test_known_disparity(self, synthetic_binary_data):
        """With known biased data, DPD should be significantly > 0."""
        data = synthetic_binary_data
        result = demographic_parity_difference(data["y_pred"], data["sensitive"])
        # The synthetic data has predicted positive rates of ~65% (A) vs ~35% (B),
        # so the expected DPD is around 0.30.  A threshold of 0.1 is conservative
        # enough to pass even with random-seed variability.
        assert result > 0.1  # Known disparity exists


class TestEqualizedOdds:
    """Validate the ``equalized_odds_difference`` metric.

    Equalized Odds Difference (EOD) measures the maximum absolute difference
    between groups in either true-positive rate (TPR) or false-positive rate
    (FPR).  A value of 0 means both groups experience identical error rates.
    """

    def test_returns_float(self, synthetic_binary_data):
        """EOD should return a float in [0, 1] for any valid input."""
        data = synthetic_binary_data
        result = equalized_odds_difference(
            data["y_true"], data["y_pred"], data["sensitive"]
        )
        assert isinstance(result, float)
        # EOD is bounded between 0 (perfect equalized odds) and 1 (max disparity)
        assert 0.0 <= result <= 1.0

    def test_perfect_equalized_odds(self):
        """When TPR and FPR are equal across groups, EOD should be ~0."""
        # Both groups have identical confusion matrices:
        #   TP=1, FN=1, TN=1, FP=0 -> TPR=0.5, FPR=0.0
        y_true = np.array([1, 1, 0, 0, 1, 1, 0, 0])
        y_pred = np.array([1, 0, 0, 0, 1, 0, 0, 0])
        sensitive = np.array(["A", "A", "A", "A", "B", "B", "B", "B"])
        result = equalized_odds_difference(y_true, y_pred, sensitive)
        # 0.01 tolerance for floating-point arithmetic on small arrays
        assert abs(result) < 0.01


# ======================== Unit Tests: Statistical ========================

class TestBootstrapCI:
    """Validate bootstrap confidence interval computation.

    The bootstrap CI should (a) contain the point estimate of the metric and
    (b) have a width that is neither zero nor implausibly large.  We use 200
    bootstrap iterations as a balance between test speed and CI stability.
    """

    def test_ci_contains_point_estimate(self, synthetic_binary_data):
        """The 95% bootstrap CI must contain the observed point estimate."""
        data = synthetic_binary_data
        point = demographic_parity_difference(data["y_pred"], data["sensitive"])
        lower, upper = bootstrap_confidence_interval(
            demographic_parity_difference,
            None,  # y_true is not needed for DPD
            data["y_pred"],
            data["sensitive"],
            n_bootstrap=200,
        )
        # By construction the point estimate should fall within its own CI
        assert lower <= point <= upper

    def test_ci_width_is_reasonable(self, synthetic_binary_data):
        """The CI width should be positive but less than the metric's full range."""
        data = synthetic_binary_data
        lower, upper = bootstrap_confidence_interval(
            demographic_parity_difference,
            None,
            data["y_pred"],
            data["sensitive"],
            n_bootstrap=200,
        )
        width = upper - lower
        # Width must be strictly positive (non-degenerate CI)
        # and less than 1.0 (the theoretical maximum range of DPD)
        assert 0 < width < 1.0


class TestEffectSize:
    """Validate the ``compute_effect_size`` function (risk ratio).

    The risk ratio is defined as P(positive | group_min) / P(positive | group_max).
    A ratio of 1.0 means equal positive rates; values further from 1 indicate
    greater disparity.
    """

    def test_risk_ratio_biased_data(self, synthetic_binary_data):
        """Biased data should yield a positive, non-unit risk ratio."""
        data = synthetic_binary_data
        ratio = compute_effect_size(data["y_pred"], data["sensitive"])
        assert isinstance(ratio, float)
        # The ratio must be positive (both groups have nonzero positive rates)
        assert ratio > 0

    def test_risk_ratio_equal_groups(self):
        """When both groups have the same positive rate, risk ratio should be ~1."""
        # Symmetric 50/50 positive rate in each group
        y_pred = np.array([1, 0, 1, 0, 1, 0, 1, 0])
        sensitive = np.array(["A", "A", "A", "A", "B", "B", "B", "B"])
        ratio = compute_effect_size(y_pred, sensitive)
        # 0.01 tolerance: with exactly equal rates, ratio should be 1.0
        assert abs(ratio - 1.0) < 0.01


# ======================== Functional Tests: Analyzer ========================

class TestFairnessAnalyzer:
    """Validate the ``FairnessAnalyzer`` facade that unifies metric computation.

    The analyzer wraps individual metrics with bootstrap CIs, effect sizes, and
    group-size metadata into a single structured result dictionary.
    """

    def test_compute_metrics_returns_dict(self, synthetic_binary_data):
        """The compute_metrics method must return a dict keyed by metric name."""
        data = synthetic_binary_data
        analyzer = FairnessAnalyzer(
            y_true=data["y_true"],
            y_pred=data["y_pred"],
            sensitive_features=data["sensitive"],
        )
        results = analyzer.compute_metrics()
        assert isinstance(results, dict)
        # DPD is always included in the default metric set
        assert "demographic_parity_difference" in results

    def test_result_structure(self, synthetic_binary_data):
        """Each metric entry must include value, CI bounds, effect size, and group sizes."""
        data = synthetic_binary_data
        analyzer = FairnessAnalyzer(
            y_true=data["y_true"],
            y_pred=data["y_pred"],
            sensitive_features=data["sensitive"],
        )
        results = analyzer.compute_metrics(metrics=["demographic_parity_difference"])
        dpd = results["demographic_parity_difference"]

        # Verify every expected key is present in the result structure
        assert "value" in dpd
        assert "ci_lower" in dpd
        assert "ci_upper" in dpd
        assert "effect_size" in dpd
        assert "group_sizes" in dpd

    def test_generate_report(self, synthetic_binary_data):
        """The text report must be a non-empty string mentioning computed metrics."""
        data = synthetic_binary_data
        analyzer = FairnessAnalyzer(
            y_true=data["y_true"],
            y_pred=data["y_pred"],
            sensitive_features=data["sensitive"],
        )
        report = analyzer.generate_report()
        assert isinstance(report, str)
        # The report should reference the primary metric by name
        assert "demographic_parity_difference" in report


# ======================== Functional Tests: Integration ========================

class TestAssertFairness:
    """Validate the ``assert_fairness`` pytest helper.

    This function is designed to be called inside CI/CD pipelines or test suites
    as a fairness gate: it raises ``AssertionError`` when a metric exceeds the
    given threshold.
    """

    def test_passes_when_fair(self):
        """When predictions are identical for both groups, the assertion should pass."""
        # Both groups have identical predictions -> DPD = 0
        y_pred = np.array([1, 0, 1, 0, 1, 0, 1, 0])
        y_true = np.array([1, 0, 1, 0, 1, 0, 1, 0])
        sensitive = np.array(["A", "A", "A", "A", "B", "B", "B", "B"])
        # Threshold of 0.5 is intentionally lenient; the point is that
        # perfectly fair data should pass even a moderately strict gate.
        assert_fairness(y_true, y_pred, sensitive, threshold=0.5)

    def test_fails_when_unfair(self, synthetic_binary_data):
        """When the synthetic bias exceeds a strict threshold, the assertion must fail."""
        data = synthetic_binary_data
        with pytest.raises(AssertionError):
            assert_fairness(
                data["y_true"],
                data["y_pred"],
                data["sensitive"],
                metric="demographic_parity_difference",
                # 0.01 is intentionally very strict -- the synthetic data has
                # a DPD of ~0.30, so this threshold guarantees a failure.
                threshold=0.01,
            )
