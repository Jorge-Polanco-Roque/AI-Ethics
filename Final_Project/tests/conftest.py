"""
Shared pytest fixtures for the Fairness Pipeline Development Toolkit test suite.

This module provides reusable synthetic datasets that simulate realistic fairness
scenarios without depending on external data sources. The fixtures are designed
to introduce *known, controlled biases* so that downstream tests can validate
that measurement, pipeline, and training components detect and mitigate those
biases correctly.

Fixture overview
----------------
- ``synthetic_binary_data``  -- Binary classification arrays with a deliberate
  demographic disparity between two groups (A and B).
- ``synthetic_credit_df``    -- A pandas DataFrame that mimics the structure of
  the German Credit dataset, used by pipeline/detection tests.
- ``train_test_arrays``      -- A deterministic train/test split derived from
  ``synthetic_binary_data``, used by training module tests.

All fixtures use a fixed random seed (42) so that test results are fully
reproducible across runs and environments.
"""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synthetic_binary_data():
    """Generate synthetic binary classification data with a sensitive attribute.

    Creates a dataset where group 'A' has a higher positive rate than group 'B',
    introducing a known demographic disparity for testing.

    Data construction rationale
    ---------------------------
    - **Group sizes** (300 A, 200 B): unequal sizes mimic real-world imbalanced
      representation and let us verify that metrics handle different-sized groups.
    - **True positive rates** (70% for A, 40% for B): the 30-percentage-point gap
      ensures a clearly detectable disparity in any demographic parity metric.
    - **Predicted positive rates** (65% for A, 35% for B): slightly lower than
      the true rates, simulating a realistic model that underestimates positives
      while still preserving inter-group disparity.
    - **Features X**: 5 standard-normal columns, intentionally uncorrelated with
      the sensitive attribute, so that any measured bias originates exclusively
      from ``y_true`` / ``y_pred``.
    """
    np.random.seed(42)
    n = 500

    # 300 samples in the privileged group (A), 200 in the unprivileged group (B)
    sensitive = np.array(["A"] * 300 + ["B"] * 200)

    y_true = np.concatenate([
        np.random.binomial(1, 0.7, 300),  # Group A: 70% positive rate
        np.random.binomial(1, 0.4, 200),  # Group B: 40% positive rate
    ])
    y_pred = np.concatenate([
        np.random.binomial(1, 0.65, 300),  # Predictions for A (slight under-prediction)
        np.random.binomial(1, 0.35, 200),  # Predictions for B (slight under-prediction)
    ])

    # Random features with no relation to the sensitive attribute
    X = np.random.randn(n, 5)

    return {
        "X": X,
        "y_true": y_true,
        "y_pred": y_pred,
        "sensitive": sensitive,
        "n": n,
    }


@pytest.fixture
def synthetic_credit_df():
    """Generate a synthetic credit DataFrame mimicking German Credit structure.

    The DataFrame contains the same column names and value ranges as a simplified
    version of the UCI German Credit dataset.  It is used by
    ``BiasDetectionEngine`` tests that require a pandas DataFrame input.

    Column design rationale
    -----------------------
    - **sex** distribution (60/40 male/female): mirrors the approximate ratio in
      the real German Credit dataset so that representation-bias tests produce
      realistic p-values.
    - **target** (70% positive rate): matches the ~70% "good credit" prevalence
      in the original dataset.
    - **income** and **credit_amount**: drawn from normal distributions and
      clipped to avoid nonsensical negative values, ensuring statistical tests
      (KS, chi-squared) behave as expected.
    """
    np.random.seed(42)
    n = 400

    df = pd.DataFrame({
        "age": np.random.randint(18, 70, n),
        "income": np.random.normal(50000, 15000, n).clip(10000),
        "credit_amount": np.random.normal(5000, 3000, n).clip(500),
        "duration": np.random.randint(6, 72, n),
        "sex": np.random.choice(["male", "female"], n, p=[0.6, 0.4]),
        "housing": np.random.choice(["own", "rent", "free"], n),
        "target": np.random.binomial(1, 0.7, n),
    })

    return df


@pytest.fixture
def train_test_arrays(synthetic_binary_data):
    """Split synthetic data into train/test arrays with a deterministic cut.

    Split rationale
    ---------------
    The split index (350) is chosen so that the training set contains samples
    from *both* groups (all 300 A-samples plus 50 of the 200 B-samples), while
    the test set is dominated by group B (150 samples) with zero or very few
    group-A samples.  This deliberate imbalance in the test partition stresses
    the fairness-aware training methods -- they must generalize their fairness
    constraints to a group distribution they have not seen in identical
    proportions during training.
    """
    data = synthetic_binary_data
    split = 350  # First 350 samples -> train, remaining 150 -> test

    return {
        "X_train": data["X"][:split],
        "X_test": data["X"][split:],
        "y_train": data["y_true"][:split],
        "y_test": data["y_true"][split:],
        "sensitive_train": data["sensitive"][:split],
        "sensitive_test": data["sensitive"][split:],
    }
