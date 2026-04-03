"""
Measurement Module for the Fairness Pipeline Development Toolkit.

Provides fairness metrics computation, statistical analysis, and integration
utilities for evaluating bias in machine learning models.

Exports:
    FairnessAnalyzer: Main class for comprehensive fairness analysis.
    assert_fairness: Pytest-compatible assertion for fairness thresholds.
    log_to_mlflow: Log fairness results to an active MLflow run.
"""

from fairness_toolkit.measurement.analyzer import FairnessAnalyzer
from fairness_toolkit.measurement.integrations import assert_fairness, log_to_mlflow

__all__ = [
    "FairnessAnalyzer",
    "assert_fairness",
    "log_to_mlflow",
]
