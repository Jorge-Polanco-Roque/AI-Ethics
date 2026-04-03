"""
Fairness Pipeline Development Toolkit
======================================

A modular, configuration-driven library for operationalizing ML fairness
across the pre-deployment lifecycle. Built for FairML Consulting.

Submodules:
    - measurement: Fairness metrics, bootstrap CIs, effect sizes, reporting
    - pipeline:    Bias detection and pre-processing transformers
    - training:    Constrained optimization, regularization, calibration

Usage:
    from fairness_toolkit.measurement import FairnessAnalyzer
    from fairness_toolkit.pipeline import DisparateImpactRemover
    from fairness_toolkit.training import ReductionsWrapper
"""

__version__ = "1.0.0"
