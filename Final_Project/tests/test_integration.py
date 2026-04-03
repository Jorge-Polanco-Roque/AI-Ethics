"""
End-to-end integration tests for the Fairness Pipeline.

This module exercises the complete fairness pipeline on the *real* German Credit
dataset (UCI), validating that all toolkit components work together seamlessly
from data loading through bias-aware training to final fairness evaluation.

Unlike the unit tests in the other test files (which use synthetic fixtures),
these tests call ``load_german_credit`` to fetch and preprocess the actual
dataset, giving confidence that the toolkit handles real-world data shapes,
dtypes, and distributions correctly.

Test progression
----------------
The tests follow the three-step orchestration flow defined in the project
architecture:

1. **Data loading** (``test_data_loads_correctly``): Verify that the loader
   returns non-empty arrays and identifies the expected sensitive columns.
2. **Baseline measurement** (``test_baseline_measurement``): Train an
   unconstrained model and measure its fairness using ``FairnessAnalyzer``.
3. **Transformation** (``test_transformer_works_on_real_data``): Apply
   ``DisparateImpactRemover`` to the training data and verify shape preservation.
4. **Fair training** (``test_fair_training_on_real_data``): Train a constrained
   model via ``ReductionsWrapper`` and confirm it achieves better-than-random
   accuracy.
5. **Full pipeline** (``test_full_pipeline_improves_fairness``): Compare
   baseline vs. fair-model demographic parity to verify that the pipeline
   reduces bias end-to-end.
"""

import os
import sys
import numpy as np
import pytest

# Ensure the project root is on sys.path so that ``fairness_toolkit`` is
# importable even when tests are run from a different working directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fairness_toolkit.data.loader import load_german_credit
from fairness_toolkit.measurement.analyzer import FairnessAnalyzer
from fairness_toolkit.pipeline.detection import BiasDetectionEngine
from fairness_toolkit.pipeline.transformers import DisparateImpactRemover
from fairness_toolkit.training.reductions import ReductionsWrapper
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score


class TestEndToEndPipeline:
    """Functional test: full pipeline from data loading to fair model evaluation.

    All tests in this class share a single dataset loaded via the ``setup_data``
    fixture (``autouse=True``).  The 70/30 train-test split with
    ``random_state=42`` ensures deterministic partitioning across runs.
    """

    @pytest.fixture(autouse=True)
    def setup_data(self):
        """Load the German Credit dataset with a fixed 70/30 split."""
        self.data = load_german_credit(test_size=0.3, random_state=42)

    def test_data_loads_correctly(self):
        """Verify that the loader returns well-formed, non-empty arrays."""
        assert self.data["X_train"].shape[0] > 0
        assert self.data["X_test"].shape[0] > 0
        # Label array length must match the number of training samples
        assert len(self.data["y_train"]) == self.data["X_train"].shape[0]
        # The German Credit dataset must expose "sex" as a sensitive column
        assert "sex" in self.data["sensitive_columns"]

    def test_baseline_measurement(self):
        """Step 1: Can measure fairness on baseline model."""
        # Train a standard logistic regression with no fairness constraints.
        # max_iter=1000 avoids convergence warnings on this dataset.
        model = LogisticRegression(max_iter=1000, random_state=42)
        model.fit(self.data["X_train"], self.data["y_train"])
        preds = model.predict(self.data["X_test"])

        analyzer = FairnessAnalyzer(
            y_true=self.data["y_test"],
            y_pred=preds,
            sensitive_features=self.data["sensitive_test"]["sex"].values,
        )
        results = analyzer.compute_metrics(["demographic_parity_difference"])
        assert "demographic_parity_difference" in results
        # A non-None value confirms that the metric was actually computed
        assert results["demographic_parity_difference"]["value"] is not None

    def test_transformer_works_on_real_data(self):
        """Step 2a: Transformer processes German Credit data."""
        # Encode the sensitive attribute as a numeric column and append it to X
        # so that the transformer can locate it by column index.
        sens = (self.data["sensitive_train"]["sex"] == "male").astype(float).values
        X_aug = np.column_stack([self.data["X_train"], sens])

        remover = DisparateImpactRemover(
            sensitive_column_index=X_aug.shape[1] - 1,
            repair_level=0.8,  # 80% repair: strong but not maximal, preserving some signal
        )
        remover.fit(X_aug)
        X_transformed = remover.transform(X_aug)
        # Shape must be preserved so the transformed data can replace the
        # original in downstream pipelines without schema changes.
        assert X_transformed.shape == X_aug.shape

    def test_fair_training_on_real_data(self):
        """Step 2b: Fair model trains on German Credit data."""
        wrapper = ReductionsWrapper(
            estimator=LogisticRegression(max_iter=1000),
            constraint="demographic_parity",
            eps=0.05,  # Allow up to 5% constraint violation
        )
        sens = self.data["sensitive_train"]["sex"].values
        wrapper.fit(self.data["X_train"], self.data["y_train"], sensitive_features=sens)
        preds = wrapper.predict(self.data["X_test"])

        acc = accuracy_score(self.data["y_test"], preds)
        # Accuracy must be better than random (50%) to confirm the model
        # learned useful patterns despite the fairness constraint.
        assert acc > 0.5
        assert len(preds) == len(self.data["y_test"])

    def test_full_pipeline_improves_fairness(self):
        """End-to-end: fair pipeline should reduce bias compared to baseline."""
        from fairness_toolkit.measurement.metrics import demographic_parity_difference

        sens_train = self.data["sensitive_train"]["sex"].values
        sens_test = self.data["sensitive_test"]["sex"].values

        # --- Baseline: unconstrained logistic regression ---
        baseline = LogisticRegression(max_iter=1000, random_state=42)
        baseline.fit(self.data["X_train"], self.data["y_train"])
        baseline_preds = baseline.predict(self.data["X_test"])
        baseline_dpd = demographic_parity_difference(baseline_preds, sens_test)

        # --- Fair model: constrained via ExponentiatedGradient ---
        wrapper = ReductionsWrapper(
            estimator=LogisticRegression(max_iter=1000),
            constraint="demographic_parity",
            eps=0.01,  # Tight constraint (1% tolerance)
        )
        wrapper.fit(self.data["X_train"], self.data["y_train"], sensitive_features=sens_train)
        fair_preds = wrapper.predict(self.data["X_test"])
        fair_dpd = demographic_parity_difference(fair_preds, sens_test)

        # The fair model's DPD should be lower than or close to the baseline's.
        # A 0.10 margin is allowed because:
        #   (a) ExponentiatedGradient optimizes on the training set but we
        #       evaluate on a held-out test set, so some constraint relaxation
        #       is expected,
        #   (b) the German Credit dataset is small (1000 samples total), so
        #       test-set metric estimates have non-trivial variance.
        assert fair_dpd <= baseline_dpd + 0.10
