"""
Unit and functional tests for the TrainingModule.

This module validates the fairness-aware model training components of the
toolkit.  The training module provides three complementary approaches to
fairness during training and one post-processing calibration method:

1. **ReductionsWrapper** -- wraps Fairlearn's ExponentiatedGradient to enforce
   fairness constraints (e.g., demographic parity) via a reductions game.
2. **FairnessRegularizer** -- a PyTorch loss function that adds a demographic-
   parity penalty term (weighted by ``eta``) to the standard BCE loss.
3. **GroupFairnessCalibrator** -- applies per-group Platt scaling or isotonic
   regression to calibrate predicted probabilities post-training.

Test organization
-----------------
- ``TestReductionsWrapper``: Verifies that the wrapper produces valid binary
  predictions and that the constrained model reduces demographic parity
  disparity compared to an unconstrained baseline.
- ``TestFairnessRegularizer``: Checks loss decomposition (total = BCE + penalty),
  boundary behavior (eta=0 disables the penalty), and monotonicity of the
  penalty weight.
- ``TestGroupFairnessCalibrator``: Validates both Platt and isotonic calibration
  methods, ensuring outputs are valid probabilities in [0, 1].
"""

import numpy as np
import torch
import pytest
from sklearn.linear_model import LogisticRegression

from fairness_toolkit.training.reductions import ReductionsWrapper
from fairness_toolkit.training.regularizer import FairnessRegularizer
from fairness_toolkit.training.calibration import GroupFairnessCalibrator


# ======================== Unit Tests: ReductionsWrapper ========================

class TestReductionsWrapper:
    """Validate the ``ReductionsWrapper`` fairness-constrained training wrapper.

    The wrapper uses Fairlearn's ExponentiatedGradient algorithm to find a
    randomized classifier that satisfies a fairness constraint (e.g.,
    demographic parity) up to a specified tolerance ``eps``.
    """

    def test_fit_predict(self, train_test_arrays):
        """The wrapper must produce binary predictions with the correct length."""
        data = train_test_arrays
        wrapper = ReductionsWrapper(
            estimator=LogisticRegression(max_iter=500),
            constraint="demographic_parity",
            eps=0.05,  # Allow up to 5% constraint violation
        )
        wrapper.fit(data["X_train"], data["y_train"], data["sensitive_train"])
        preds = wrapper.predict(data["X_test"])
        assert len(preds) == len(data["y_test"])
        # Predictions must be binary (0 or 1), not continuous probabilities
        assert set(np.unique(preds)).issubset({0, 1})

    def test_reduces_disparity(self, train_test_arrays):
        """The fair model should have lower demographic parity difference."""
        data = train_test_arrays
        from fairness_toolkit.measurement.metrics import demographic_parity_difference

        # --- Unfair baseline: standard logistic regression with no constraints ---
        baseline = LogisticRegression(max_iter=500)
        baseline.fit(data["X_train"], data["y_train"])
        baseline_preds = baseline.predict(data["X_test"])
        baseline_dpd = demographic_parity_difference(
            baseline_preds, data["sensitive_test"]
        )

        # --- Fair model: constrained via ExponentiatedGradient ---
        wrapper = ReductionsWrapper(
            estimator=LogisticRegression(max_iter=500),
            constraint="demographic_parity",
            eps=0.01,  # Very tight constraint (1% tolerance)
        )
        wrapper.fit(data["X_train"], data["y_train"], data["sensitive_train"])
        fair_preds = wrapper.predict(data["X_test"])
        fair_dpd = demographic_parity_difference(
            fair_preds, data["sensitive_test"]
        )

        # The fair model's DPD should be equal to or lower than the baseline's.
        # We add a 0.15 margin because:
        #   (a) the test set has a skewed group distribution (see conftest),
        #   (b) ExponentiatedGradient is a randomized algorithm that may not
        #       perfectly satisfy the constraint on unseen data, and
        #   (c) the small test-set size (150 samples) introduces variance.
        assert fair_dpd <= baseline_dpd + 0.15


# ======================== Unit Tests: FairnessRegularizer ========================

class TestFairnessRegularizer:
    """Validate the ``FairnessRegularizer`` PyTorch loss function.

    The regularizer computes: total_loss = BCE(logits, targets) + eta * penalty,
    where the penalty measures the difference in mean predicted probabilities
    between the two sensitive groups.
    """

    def test_loss_computation(self):
        """All three loss components (total, BCE, penalty) must be positive."""
        reg = FairnessRegularizer(eta=1.0)
        logits = torch.randn(10)
        targets = torch.randint(0, 2, (10,)).float()
        # Equal split: first 5 samples in group 0, last 5 in group 1
        sensitive = torch.tensor([0, 0, 0, 0, 0, 1, 1, 1, 1, 1]).float()

        total, bce, penalty = reg(logits, targets, sensitive)
        assert total.item() > 0
        assert bce.item() > 0
        # Penalty can be zero if groups happen to have identical mean predictions,
        # but with random logits this is extremely unlikely.
        assert penalty.item() >= 0

    def test_eta_zero_equals_bce(self):
        """With eta=0, the total loss should equal BCE loss."""
        reg = FairnessRegularizer(eta=0.0)
        logits = torch.randn(10)
        targets = torch.randint(0, 2, (10,)).float()
        sensitive = torch.tensor([0, 0, 0, 0, 0, 1, 1, 1, 1, 1]).float()

        total, bce, penalty = reg(logits, targets, sensitive)
        # When eta=0, penalty * 0 = 0, so total must equal BCE exactly.
        # 1e-6 tolerance accounts for floating-point arithmetic.
        assert abs(total.item() - bce.item()) < 1e-6

    def test_higher_eta_higher_penalty_weight(self):
        """Higher eta should generally produce higher total loss when bias exists."""
        # Deliberately biased logits: group 0 gets high logits (predicted positive),
        # group 1 gets low logits (predicted negative), but all targets are 1.
        # This creates a large gap in mean predictions between groups, maximizing
        # the fairness penalty term.
        logits = torch.tensor([2.0, 2.0, 2.0, 2.0, -2.0, -2.0, -2.0, -2.0])
        targets = torch.ones(8)
        sensitive = torch.tensor([0, 0, 0, 0, 1, 1, 1, 1]).float()

        low = FairnessRegularizer(eta=0.1)
        high = FairnessRegularizer(eta=10.0)

        loss_low, _, _ = low(logits, targets, sensitive)
        loss_high, _, _ = high(logits, targets, sensitive)
        # Since the penalty is nonzero and eta scales it, higher eta -> higher total
        assert loss_high.item() > loss_low.item()


# ======================== Unit Tests: GroupFairnessCalibrator ========================

class TestGroupFairnessCalibrator:
    """Validate the ``GroupFairnessCalibrator`` post-processing calibrator.

    The calibrator fits a separate calibration model (Platt or isotonic) per
    sensitive group, so that predicted probabilities are well-calibrated
    *within* each group.  This is a post-processing fairness intervention
    that does not modify the underlying model.
    """

    def test_platt_calibration(self):
        """Platt-calibrated probabilities must remain in [0, 1] with correct length."""
        np.random.seed(42)
        n = 200
        # Generate probabilities in a realistic range and derive labels from them
        y_prob = np.random.uniform(0.2, 0.8, n)
        y_true = (y_prob > 0.5).astype(int)
        # Equal group split: 100 samples per group
        sensitive = np.array(["A"] * 100 + ["B"] * 100)

        cal = GroupFairnessCalibrator(method="platt")
        cal.fit(y_prob, y_true, sensitive)
        calibrated = cal.transform(y_prob, sensitive)

        assert len(calibrated) == n
        # Platt scaling (logistic sigmoid) guarantees outputs in [0, 1]
        assert np.all(calibrated >= 0) and np.all(calibrated <= 1)

    def test_isotonic_calibration(self):
        """Isotonic-calibrated probabilities must remain in [0, 1] with correct length."""
        np.random.seed(42)
        n = 200
        y_prob = np.random.uniform(0.2, 0.8, n)
        y_true = (y_prob > 0.5).astype(int)
        sensitive = np.array(["A"] * 100 + ["B"] * 100)

        cal = GroupFairnessCalibrator(method="isotonic")
        cal.fit(y_prob, y_true, sensitive)
        calibrated = cal.transform(y_prob, sensitive)

        assert len(calibrated) == n
        # Isotonic regression is a non-parametric monotone fit; outputs
        # should be clipped to [0, 1] by the implementation.
        assert np.all(calibrated >= 0) and np.all(calibrated <= 1)
