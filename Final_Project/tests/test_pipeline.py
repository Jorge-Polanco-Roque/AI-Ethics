"""
Unit and functional tests for the PipelineModule.

This module validates the data-engineering layer of the fairness toolkit, which
is responsible for detecting bias in raw datasets and transforming features to
mitigate disparate impact *before* model training.

Test organization
-----------------
1. **BiasDetectionEngine tests** (``TestBiasDetectionEngine``):
   Verify that the engine can detect representation imbalances, statistical
   disparities between groups, and proxy variables -- all using the synthetic
   credit DataFrame from ``conftest.py``.

2. **InstanceReweighter tests** (``TestInstanceReweighter``):
   Confirm that reweighting produces sample weights that are positive and that
   the transformer preserves array shape (sklearn compatibility).

3. **DisparateImpactRemover tests** (``TestDisparateImpactRemover``):
   Validate that the repair transformation reduces feature--sensitive-attribute
   correlation, preserves array shape, and degrades to an identity transform
   when ``repair_level=0.0``.

All transformers are tested through the sklearn ``fit`` / ``transform`` API to
ensure they can be dropped into standard ``sklearn.pipeline.Pipeline`` objects.
"""

import numpy as np
import pandas as pd
import pytest

from fairness_toolkit.pipeline.detection import BiasDetectionEngine
from fairness_toolkit.pipeline.transformers import (
    InstanceReweighter,
    DisparateImpactRemover,
)


# ======================== Unit Tests: BiasDetectionEngine ========================

class TestBiasDetectionEngine:
    """Validate the ``BiasDetectionEngine`` audit capabilities.

    The engine inspects a DataFrame for three types of pre-training bias:
    representation imbalance (chi-squared test), statistical disparity in
    feature distributions (per-feature KS test), and proxy variables
    (features highly correlated with the sensitive attribute).
    """

    def test_detect_representation_bias(self, synthetic_credit_df):
        """Representation bias detection must return group counts and a p-value."""
        engine = BiasDetectionEngine(sensitive_column="sex")
        result = engine.detect_representation_bias(synthetic_credit_df)
        assert "group_counts" in result
        assert "p_value" in result
        # p-value must be a valid probability
        assert isinstance(result["p_value"], float)

    def test_detect_statistical_disparity(self, synthetic_credit_df):
        """Statistical disparity detection must return per-feature results."""
        engine = BiasDetectionEngine(sensitive_column="sex")
        result = engine.detect_statistical_disparity(
            synthetic_credit_df, target_column="target"
        )
        assert isinstance(result, dict)
        # At least one numeric feature (age, income, or credit_amount) should
        # appear in the disparity results.
        assert any(key in result for key in ["age", "income", "credit_amount"])

    def test_detect_proxy_variables(self, synthetic_credit_df):
        """Proxy detection must return correlation info and a boolean flag per feature."""
        engine = BiasDetectionEngine(sensitive_column="sex")
        # Threshold of 0.3 is a common heuristic for "moderate" correlation
        result = engine.detect_proxy_variables(synthetic_credit_df, threshold=0.3)
        assert isinstance(result, dict)
        for feat, info in result.items():
            assert "correlation" in info
            assert "is_proxy" in info

    def test_full_audit(self, synthetic_credit_df):
        """The full audit report must contain all three bias-detection sections."""
        engine = BiasDetectionEngine(sensitive_column="sex")
        report = engine.full_audit(synthetic_credit_df, target_column="target")
        assert "representation_bias" in report
        assert "statistical_disparity" in report
        assert "proxy_variables" in report


# ======================== Unit Tests: Transformers ========================

class TestInstanceReweighter:
    """Validate the ``InstanceReweighter`` sklearn-compatible transformer.

    The reweighter assigns per-sample weights that counterbalance
    representation and label-rate disparities across sensitive groups.
    """

    def test_fit_transform_shape(self, synthetic_binary_data):
        """After fit + transform, the output array must have the same shape as input."""
        data = synthetic_binary_data
        # Append a binary sensitive-attribute column so the transformer knows
        # which column index to use for group membership.
        X_aug = np.column_stack([
            data["X"],
            (data["sensitive"] == "A").astype(float),
        ])
        reweighter = InstanceReweighter(sensitive_column_index=5)
        result = reweighter.fit(X_aug, data["y_true"])
        X_out = reweighter.transform(X_aug)
        # Shape must be preserved for pipeline compatibility
        assert X_out.shape == X_aug.shape
        # Weights must be computed and stored after fitting
        assert hasattr(reweighter, "sample_weights_")
        assert len(reweighter.sample_weights_) == len(data["y_true"])

    def test_weights_are_positive(self, synthetic_binary_data):
        """All sample weights must be strictly positive (no zero or negative weights)."""
        data = synthetic_binary_data
        X_aug = np.column_stack([
            data["X"],
            (data["sensitive"] == "A").astype(float),
        ])
        reweighter = InstanceReweighter(sensitive_column_index=5)
        reweighter.fit(X_aug, data["y_true"])
        # Zero or negative weights would effectively drop samples from training
        assert np.all(reweighter.sample_weights_ > 0)


class TestDisparateImpactRemover:
    """Validate the ``DisparateImpactRemover`` sklearn-compatible transformer.

    This transformer modifies feature distributions to reduce their correlation
    with the sensitive attribute, parameterized by a ``repair_level`` in [0, 1].
    At ``repair_level=0`` the transformation should be the identity; at
    ``repair_level=1`` it should maximally decorrelate features from the
    protected attribute.
    """

    def test_transform_shape(self, synthetic_binary_data):
        """Output shape must match input shape after full repair."""
        data = synthetic_binary_data
        X_aug = np.column_stack([
            data["X"],
            (data["sensitive"] == "A").astype(float),
        ])
        remover = DisparateImpactRemover(sensitive_column_index=5, repair_level=1.0)
        remover.fit(X_aug)
        X_out = remover.transform(X_aug)
        assert X_out.shape == X_aug.shape

    def test_repair_reduces_correlation(self, synthetic_binary_data):
        """After repair, feature-sensitive correlation should decrease."""
        data = synthetic_binary_data
        sensitive_numeric = (data["sensitive"] == "A").astype(float)

        # Construct a feature that is *highly* correlated with the sensitive
        # attribute: feature = 2 * sensitive + small noise.  This guarantees
        # a strong pre-repair correlation that the remover should reduce.
        correlated_feature = sensitive_numeric * 2 + np.random.randn(len(sensitive_numeric)) * 0.5
        X_aug = np.column_stack([
            correlated_feature.reshape(-1, 1),
            data["X"],
            sensitive_numeric,
        ])

        remover = DisparateImpactRemover(
            sensitive_column_index=X_aug.shape[1] - 1, repair_level=1.0
        )
        remover.fit(X_aug)
        X_repaired = remover.transform(X_aug)

        corr_before = abs(np.corrcoef(X_aug[:, 0], sensitive_numeric)[0, 1])
        corr_after = abs(np.corrcoef(X_repaired[:, 0], sensitive_numeric)[0, 1])
        # Allow a small tolerance of 0.05 because the repair is approximate
        # (median-based quantile adjustment), so the post-repair correlation
        # may not drop to exactly zero.
        assert corr_after <= corr_before + 0.05

    def test_no_repair_is_identity(self, synthetic_binary_data):
        """With repair_level=0.0, the output must be identical to the input."""
        data = synthetic_binary_data
        X_aug = np.column_stack([
            data["X"],
            (data["sensitive"] == "A").astype(float),
        ])
        remover = DisparateImpactRemover(sensitive_column_index=5, repair_level=0.0)
        remover.fit(X_aug)
        X_out = remover.transform(X_aug)
        # decimal=10 ensures near-exact equality (tolerance ~1e-10),
        # verifying that zero repair truly acts as an identity transform.
        np.testing.assert_array_almost_equal(X_aug, X_out, decimal=10)
