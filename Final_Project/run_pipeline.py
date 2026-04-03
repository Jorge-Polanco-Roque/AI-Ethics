#!/usr/bin/env python3
"""
Fairness Pipeline Orchestrator
===============================

This is the main entry point for the Fairness Pipeline Development Toolkit.
It reads a declarative YAML configuration file (config.yml) and executes
a three-step fairness workflow:

    Step 1 — Baseline Measurement
        Train an unconstrained model and measure its fairness metrics
        (DPD, EOD) with bootstrap confidence intervals. This establishes
        the "before" snapshot.

    Step 2 — Transform & Train
        (a) Apply a pre-processing transformer (e.g., DisparateImpactRemover)
            to reduce feature-level bias.
        (b) Train a fair model using a constrained optimization method
            (e.g., ReductionsWrapper with demographic parity constraint).

    Step 3 — Final Validation
        Re-measure the same fairness metrics on the fair model's predictions,
        compare against the baseline, issue a PASS/FAIL verdict, and log
        everything to MLflow (metrics, model artifact, config file).

The entire pipeline is deterministic given the same config.yml and random
seeds, enabling reproducible fairness audits.

Usage
-----
    python run_pipeline.py                          # uses config.yml
    python run_pipeline.py --config custom.yml      # uses a custom config

Exit codes:
    0 = pipeline PASSED (primary fairness metric <= threshold)
    1 = pipeline FAILED (primary fairness metric > threshold)
"""

import argparse
import sys
import os
import warnings

import yaml
import numpy as np
import pandas as pd
import mlflow
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

# Ensure the project root is on the Python path so that
# `fairness_toolkit` can be imported when running the script directly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fairness_toolkit.data.loader import load_german_credit
from fairness_toolkit.measurement.analyzer import FairnessAnalyzer
from fairness_toolkit.measurement.integrations import log_to_mlflow
from fairness_toolkit.pipeline.transformers import DisparateImpactRemover, InstanceReweighter
from fairness_toolkit.training.reductions import ReductionsWrapper

# Suppress sklearn FutureWarnings to keep pipeline output clean.
warnings.filterwarnings("ignore", category=FutureWarning)


# ===========================================================================
# Factory functions — translate config strings into Python objects
# ===========================================================================

def load_config(config_path: str) -> dict:
    """Load the pipeline configuration from a YAML file.

    Parameters
    ----------
    config_path : str
        Path to the YAML configuration file.

    Returns
    -------
    dict
        Parsed configuration dictionary.
    """
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    print(f"[CONFIG] Loaded configuration from: {config_path}")
    return config


def get_transformer(config: dict, sensitive_col_index: int):
    """Instantiate the pre-processing transformer specified in config.

    This factory reads ``config['preprocessing']['transformer']`` and
    returns the corresponding sklearn-compatible transformer object.

    Parameters
    ----------
    config : dict
        Full pipeline configuration.
    sensitive_col_index : int
        Column index of the sensitive attribute in the augmented
        feature matrix (typically the last column).

    Returns
    -------
    TransformerMixin
        A fitted-ready transformer (DisparateImpactRemover or
        InstanceReweighter).
    """
    name = config["preprocessing"]["transformer"]
    params = config["preprocessing"].get("params", {})

    if name == "DisparateImpactRemover":
        return DisparateImpactRemover(
            sensitive_column_index=sensitive_col_index,
            repair_level=params.get("repair_level", 1.0),
        )
    elif name == "InstanceReweighter":
        return InstanceReweighter(sensitive_column_index=sensitive_col_index)
    else:
        raise ValueError(f"Unknown transformer: {name}")


def get_trainer(config: dict):
    """Instantiate the fair training method specified in config.

    This factory reads ``config['training']['method']`` and returns
    the corresponding wrapper with the fairness constraint and base
    estimator configured.

    Parameters
    ----------
    config : dict
        Full pipeline configuration.

    Returns
    -------
    ReductionsWrapper
        A ready-to-fit fair training wrapper.
    """
    method = config["training"]["method"]
    params = config["training"].get("params", {})
    base_est_name = config["training"].get("base_estimator", "LogisticRegression")

    # Instantiate the base sklearn estimator
    if base_est_name == "LogisticRegression":
        base_estimator = LogisticRegression(max_iter=1000, random_state=42)
    else:
        raise ValueError(f"Unknown base estimator: {base_est_name}")

    # Wrap it with the fairness constraint
    if method == "ReductionsWrapper":
        return ReductionsWrapper(
            estimator=base_estimator,
            constraint=params.get("constraint", "demographic_parity"),
            eps=params.get("eps", 0.01),
        )
    else:
        raise ValueError(f"Unknown training method: {method}")


# ===========================================================================
# Report card — human-readable comparison of baseline vs. final
# ===========================================================================

def print_report_card(baseline_results: dict, final_results: dict, config: dict):
    """Print a side-by-side comparison of baseline vs. final fairness metrics.

    For each metric, shows the baseline value, final value, absolute change,
    percentage change, and 95% CI of the final measurement. Concludes with
    a PASS/FAIL verdict based on the primary fairness metric and threshold.

    Parameters
    ----------
    baseline_results : dict
        Output of FairnessAnalyzer.compute_metrics() for the baseline model.
    final_results : dict
        Output of FairnessAnalyzer.compute_metrics() for the fair model.
    config : dict
        Pipeline configuration (used to read the validation threshold).

    Returns
    -------
    bool
        True if the primary metric is within the threshold (PASS).
    """
    primary_metric = config["validation"]["primary_fairness_metric"]
    threshold = config["validation"]["threshold"]

    print("\n" + "=" * 60)
    print("         FAIRNESS PIPELINE - REPORT CARD")
    print("=" * 60)

    # Compare each metric: baseline vs. final
    for metric_name in baseline_results:
        baseline_val = baseline_results[metric_name]["value"]
        final_val = final_results[metric_name]["value"]
        improvement = baseline_val - final_val
        # Percentage improvement relative to the baseline value
        # (guard against division by zero with a small epsilon)
        pct = (improvement / max(abs(baseline_val), 1e-10)) * 100

        print(f"\n  Metric: {metric_name}")
        print(f"    Baseline : {baseline_val:.4f}")
        print(f"    Final    : {final_val:.4f}")
        print(f"    Change   : {improvement:+.4f} ({pct:+.1f}%)")

        # Show the bootstrap CI for the final measurement
        if metric_name in final_results:
            ci = (final_results[metric_name].get("ci_lower", "N/A"),
                  final_results[metric_name].get("ci_upper", "N/A"))
            if isinstance(ci[0], float):
                print(f"    95% CI   : [{ci[0]:.4f}, {ci[1]:.4f}]")

    # --- PASS/FAIL verdict ---
    final_primary = final_results.get(primary_metric, {}).get("value", float("inf"))
    passed = final_primary <= threshold

    print(f"\n  {'=' * 50}")
    print(f"  Primary Metric : {primary_metric}")
    print(f"  Final Value    : {final_primary:.4f}")
    print(f"  Threshold      : {threshold:.4f}")
    print(f"  Status         : {'PASS' if passed else 'FAIL'}")
    print("=" * 60)

    return passed


# ===========================================================================
# Main pipeline — the three-step orchestration
# ===========================================================================

def main(config_path: str = "config.yml"):
    """Execute the three-step fairness pipeline.

    This is the core orchestration function. It loads data, runs all
    three steps, logs results to MLflow, and returns whether the
    pipeline passed validation.

    Parameters
    ----------
    config_path : str
        Path to the YAML configuration file.

    Returns
    -------
    bool
        True if the pipeline passed (primary metric <= threshold).
    """

    # ---- Load Configuration ----
    config = load_config(config_path)
    sensitive_attr = config["sensitive_attribute"]

    # ---- Load Data ----
    print("\n[DATA] Loading German Credit dataset...")
    data = load_german_credit(
        test_size=config["dataset"].get("test_size", 0.3),
        random_state=config["dataset"].get("random_state", 42),
    )

    X_train = data["X_train"]
    X_test = data["X_test"]
    y_train = data["y_train"]
    y_test = data["y_test"]
    # Extract the sensitive attribute as a 1-D array of group labels
    sens_train = data["sensitive_train"][sensitive_attr].values
    sens_test = data["sensitive_test"][sensitive_attr].values

    print(f"  Train: {X_train.shape[0]} samples | Test: {X_test.shape[0]} samples")
    print(f"  Sensitive attribute: '{sensitive_attr}'")

    # ---- Setup MLflow ----
    # Configure the tracking URI and experiment name from config.yml
    # so that results are logged to the expected location.
    mlflow_config = config.get("mlflow", {})
    mlflow.set_tracking_uri(mlflow_config.get("tracking_uri", "mlruns"))
    mlflow.set_experiment(mlflow_config.get("experiment_name", "fairness_pipeline"))

    with mlflow.start_run(run_name="fairness_pipeline_run"):

        # Log the config file itself as an artifact for full reproducibility:
        # anyone reviewing this run can retrieve the exact settings used.
        mlflow.log_artifact(config_path)

        # ============================================================
        # STEP 1: BASELINE MEASUREMENT
        # ============================================================
        # Train an unconstrained model (no fairness intervention) to
        # establish how much bias the raw pipeline produces.
        print("\n" + "=" * 60)
        print("  STEP 1: BASELINE MEASUREMENT")
        print("=" * 60)

        baseline_model = LogisticRegression(max_iter=1000, random_state=42)
        baseline_model.fit(X_train, y_train)
        baseline_preds = baseline_model.predict(X_test)
        baseline_acc = accuracy_score(y_test, baseline_preds)

        print(f"  Baseline model accuracy: {baseline_acc:.4f}")

        # Compute fairness metrics with bootstrap CIs on the baseline
        baseline_analyzer = FairnessAnalyzer(
            y_true=y_test,
            y_pred=baseline_preds,
            sensitive_features=sens_test,
        )
        metric_names = config["baseline"].get("metrics", ["demographic_parity_difference"])
        baseline_results = baseline_analyzer.compute_metrics(metrics=metric_names)

        # Print a summary of baseline fairness
        print("\n  Baseline Fairness Report:")
        for name, result in baseline_results.items():
            print(f"    {name}: {result['value']:.4f} "
                  f"(CI: [{result.get('ci_lower', 0):.4f}, {result.get('ci_upper', 0):.4f}])")

        # Log baseline metrics to MLflow
        mlflow.log_metric("baseline_accuracy", baseline_acc)
        for name, result in baseline_results.items():
            mlflow.log_metric(f"baseline_{name}", result["value"])

        # ============================================================
        # STEP 2: TRANSFORM DATA & TRAIN FAIR MODEL
        # ============================================================
        print("\n" + "=" * 60)
        print("  STEP 2: TRANSFORM DATA & TRAIN FAIR MODEL")
        print("=" * 60)

        # --- 2a: Apply pre-processing transformer ---
        # The transformer needs the sensitive attribute as a column in X
        # to identify group membership during repair. We append it as the
        # last column (binary encoded: 1 for first group, 0 for others),
        # then remove it after transformation so the model never sees it.
        sens_col_idx = X_train.shape[1]
        unique_groups = np.unique(sens_train)
        X_train_aug = np.column_stack([X_train, (sens_train == unique_groups[0]).astype(float)])
        X_test_aug = np.column_stack([X_test, (sens_test == unique_groups[0]).astype(float)])

        transformer = get_transformer(config, sensitive_col_index=sens_col_idx)
        print(f"  Applying transformer: {config['preprocessing']['transformer']}")

        transformer.fit(X_train_aug, y_train)
        X_train_transformed = transformer.transform(X_train_aug)
        X_test_transformed = transformer.transform(X_test_aug)

        # Strip the appended sensitive column — the model should learn
        # from debiased features, NOT from the protected attribute itself.
        X_train_fair = X_train_transformed[:, :sens_col_idx]
        X_test_fair = X_test_transformed[:, :sens_col_idx]

        # --- 2b: Train fair model ---
        # The ReductionsWrapper receives the original (string) sensitive
        # labels so that Fairlearn can compute constraint violations
        # per group during the exponentiated gradient iterations.
        trainer = get_trainer(config)
        print(f"  Training with: {config['training']['method']}")

        trainer.fit(X_train_fair, y_train, sensitive_features=sens_train)
        fair_preds = trainer.predict(X_test_fair)
        fair_acc = accuracy_score(y_test, fair_preds)

        print(f"  Fair model accuracy: {fair_acc:.4f}")

        # ============================================================
        # STEP 3: FINAL VALIDATION
        # ============================================================
        # Re-measure fairness on the fair model's predictions using the
        # same FairnessAnalyzer and metrics as Step 1. This ensures an
        # apples-to-apples comparison.
        print("\n" + "=" * 60)
        print("  STEP 3: FINAL VALIDATION")
        print("=" * 60)

        final_analyzer = FairnessAnalyzer(
            y_true=y_test,
            y_pred=fair_preds,
            sensitive_features=sens_test,
        )
        final_results = final_analyzer.compute_metrics(metrics=metric_names)

        # Log final metrics to MLflow
        mlflow.log_metric("final_accuracy", fair_acc)
        for name, result in final_results.items():
            mlflow.log_metric(f"final_{name}", result["value"])

        # Log the primary performance metric (e.g., accuracy)
        perf_metric = config["validation"].get("primary_performance_metric", "accuracy")
        mlflow.log_metric(perf_metric, fair_acc)

        # Log the trained fair model as an MLflow artifact so it can
        # be retrieved, deployed, or audited later.
        mlflow.sklearn.log_model(trainer, "fair_model")

        # Print the comparison report card and determine PASS/FAIL
        passed = print_report_card(baseline_results, final_results, config)

        # Log the validation outcome as a binary metric (1=PASS, 0=FAIL)
        mlflow.log_metric("validation_passed", int(passed))

    return passed


# ===========================================================================
# CLI entry point
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fairness Pipeline Orchestrator — executes the 3-step "
                    "fairness workflow defined in config.yml."
    )
    parser.add_argument(
        "--config",
        default="config.yml",
        help="Path to the YAML configuration file (default: config.yml)",
    )
    args = parser.parse_args()

    # Run the pipeline; exit with code 0 (PASS) or 1 (FAIL)
    success = main(args.config)
    sys.exit(0 if success else 1)
