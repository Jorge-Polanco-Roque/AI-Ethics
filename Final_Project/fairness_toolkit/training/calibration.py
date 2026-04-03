"""Post-processing group-wise calibration for fairness.

This module implements a post-processing calibrator that fits independent
calibration models for each demographic group.  By calibrating predicted
probabilities *within* each group, systematic over- or under-confidence
that disproportionately affects certain groups can be corrected, improving
both calibration and fairness simultaneously.

Mathematical Foundations
------------------------

**Why Group-Wise Calibration?**

A model is said to be calibrated if P(Y=1 | f(X)=p) = p, i.e., among all
samples where the model predicts probability p, the true positive rate is
indeed p.  However, a model can be well-calibrated overall yet poorly
calibrated within specific demographic groups.  Group-wise calibration fits
a separate mapping f_g for each group g, ensuring that:

    P(Y=1 | f_g(X)=p, G=g) = p  for all groups g

**Platt Scaling (Logistic Regression on Log-Odds)**

Platt scaling (Platt, 1999) learns an affine transformation of the model's
log-odds (logit of the predicted probability) followed by a sigmoid::

    p_calibrated = sigma(a * logit(p_raw) + b)

where logit(p) = log(p / (1 - p)) and sigma is the sigmoid function.

Implementation details:
    1. Raw probabilities are clipped to [eps, 1 - eps] to avoid log(0).
    2. Log-odds features are computed: X_lr = log(p / (1 - p)).
    3. A LogisticRegression with very large C (1e10, effectively no
       regularization) is fitted on X_lr against the true labels.
    4. At prediction time, the same log-odds transformation is applied
       and ``predict_proba`` returns the calibrated probabilities.

This approach has two learnable parameters (slope a and intercept b) and
is therefore robust even with small calibration sets.

**Isotonic Regression**

Isotonic regression (Zadrozny & Elkan, 2002) fits a non-parametric,
monotonically non-decreasing step function from raw probabilities to
calibrated probabilities.  It is more flexible than Platt scaling (it
can model non-sigmoid calibration curves) but requires more data to
avoid overfitting.

Configuration:
    - ``y_min=0.0, y_max=1.0``: constrains outputs to valid probabilities.
    - ``out_of_bounds='clip'``: extrapolates by clipping to the nearest
      observed value, which is safer than raising an error for test-time
      predictions outside the training range.

References
----------
.. [1] Platt, J.C. (1999). "Probabilistic Outputs for Support Vector
       Machines and Comparisons to Regularized Likelihood Methods."
       Advances in Large Margin Classifiers.
.. [2] Zadrozny, B. & Elkan, C. (2002). "Transforming Classifier Scores
       into Accurate Multiclass Probability Estimates." KDD 2002.
.. [3] Pleiss, G. et al. (2017). "On Fairness and Calibration." NeurIPS 2017.
"""

from __future__ import annotations

from typing import Dict, Union

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


class GroupFairnessCalibrator:
    """Post-processing calibrator that fits separate calibration models per demographic group.

    For each unique value in ``sensitive_features``, an independent calibration
    model is trained so that predicted probabilities are well-calibrated
    *within* each group.  This can reduce fairness violations that arise from
    differential miscalibration (e.g., the model being overconfident for one
    group and underconfident for another).

    Supported methods:

    * **platt** -- Platt scaling via ``LogisticRegression`` on log-odds.
      Best for roughly sigmoid-shaped calibration curves and small
      calibration sets (only 2 parameters to learn).
    * **isotonic** -- Non-parametric ``IsotonicRegression``.
      Best for complex calibration curves when sufficient data is
      available (typically > 1000 samples per group).

    Parameters
    ----------
    method : str
        ``'platt'`` or ``'isotonic'``.

    Examples
    --------
    >>> cal = GroupFairnessCalibrator(method='platt')
    >>> cal.fit(y_prob_val, y_true_val, sensitive_val)
    >>> calibrated = cal.transform(y_prob_test, sensitive_test)
    """

    _SUPPORTED_METHODS = {"platt", "isotonic"}

    def __init__(self, method: str = "platt"):
        if method not in self._SUPPORTED_METHODS:
            raise ValueError(
                f"Unknown method '{method}'. Choose from {sorted(self._SUPPORTED_METHODS)}."
            )
        self.method = method
        # Dictionary mapping group identifier -> fitted calibrator object.
        self._calibrators: Dict[Union[int, str], object] = {}
        self._is_fitted = False

    def fit(
        self,
        y_prob: np.ndarray,
        y_true: np.ndarray,
        sensitive_features: np.ndarray,
    ) -> "GroupFairnessCalibrator":
        """Fit one calibration model per demographic group.

        A separate calibrator is trained for each unique value in
        ``sensitive_features``, using only the samples belonging to that
        group.  This ensures that calibration corrections are tailored to
        each group's specific miscalibration pattern.

        Parameters
        ----------
        y_prob : array-like of shape (n_samples,)
            Raw predicted probabilities from the base model (values in
            [0, 1]).
        y_true : array-like of shape (n_samples,)
            Binary ground-truth labels (0 or 1).
        sensitive_features : array-like of shape (n_samples,)
            Group membership for each sample.

        Returns
        -------
        self : GroupFairnessCalibrator
        """
        y_prob = np.asarray(y_prob, dtype=np.float64)
        y_true = np.asarray(y_true, dtype=np.float64)
        sensitive_features = np.asarray(sensitive_features)

        groups = np.unique(sensitive_features)

        for group in groups:
            # Isolate samples belonging to this group.
            mask = sensitive_features == group
            probs_g = y_prob[mask]
            labels_g = y_true[mask]

            # Fit the chosen calibration model on this group's data.
            if self.method == "platt":
                calibrator = self._fit_platt(probs_g, labels_g)
            else:
                calibrator = self._fit_isotonic(probs_g, labels_g)

            self._calibrators[group] = calibrator

        self._is_fitted = True
        return self

    @staticmethod
    def _fit_platt(
        probs: np.ndarray, labels: np.ndarray
    ) -> LogisticRegression:
        """Fit Platt scaling (logistic regression on log-odds).

        The transformation pipeline is:
            1. Clip probabilities to [eps, 1 - eps] to prevent log(0).
            2. Compute log-odds: logit(p) = log(p / (1 - p)).
            3. Fit a logistic regression on logit(p) vs true labels.

        The very large C (1e10) effectively disables L2 regularization,
        because Platt scaling should learn the exact affine recalibration
        a * logit(p) + b without shrinkage.  With only 1 feature and 2
        parameters, overfitting is not a concern.

        Parameters
        ----------
        probs : ndarray of shape (n,)
            Raw probabilities for a single group.
        labels : ndarray of shape (n,)
            True binary labels for that group.

        Returns
        -------
        lr : LogisticRegression
            Fitted Platt scaler.
        """
        eps = 1e-8
        # Clip to avoid numerical issues with log(0) or log(negative).
        probs_clipped = np.clip(probs, eps, 1.0 - eps)
        # Convert to log-odds space: this is the natural input for a
        # logistic regression recalibrator.  If the original model were
        # perfectly calibrated, the fitted LR would learn a=1, b=0.
        X = np.log(probs_clipped / (1.0 - probs_clipped)).reshape(-1, 1)
        lr = LogisticRegression(solver="lbfgs", max_iter=1000, C=1e10)
        lr.fit(X, labels)
        return lr

    @staticmethod
    def _fit_isotonic(
        probs: np.ndarray, labels: np.ndarray
    ) -> IsotonicRegression:
        """Fit isotonic regression calibrator.

        Isotonic regression learns a non-parametric monotone mapping from
        raw probabilities to calibrated probabilities.  The monotonicity
        constraint ensures that higher raw scores always map to higher
        (or equal) calibrated probabilities.

        Parameters
        ----------
        probs : ndarray of shape (n,)
            Raw probabilities for a single group.
        labels : ndarray of shape (n,)
            True binary labels for that group.

        Returns
        -------
        ir : IsotonicRegression
            Fitted isotonic calibrator.
        """
        ir = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        ir.fit(probs, labels)
        return ir

    def transform(
        self,
        y_prob: np.ndarray,
        sensitive_features: np.ndarray,
    ) -> np.ndarray:
        """Apply group-specific calibration to raw probabilities.

        Each sample's probability is recalibrated using the calibrator
        that was fitted for its demographic group.  This ensures that
        the calibration correction is appropriate for that group's
        specific miscalibration pattern.

        Parameters
        ----------
        y_prob : array-like of shape (n_samples,)
            Raw predicted probabilities to calibrate.
        sensitive_features : array-like of shape (n_samples,)
            Group membership for each sample (must contain only groups
            seen during ``fit``).

        Returns
        -------
        calibrated : ndarray of shape (n_samples,)
            Calibrated probabilities.

        Raises
        ------
        RuntimeError
            If the calibrator has not been fitted.
        KeyError
            If a group in ``sensitive_features`` was not seen during fit.
        """
        if not self._is_fitted:
            raise RuntimeError(
                "GroupFairnessCalibrator is not fitted. Call .fit() first."
            )

        y_prob = np.asarray(y_prob, dtype=np.float64)
        sensitive_features = np.asarray(sensitive_features)
        calibrated = np.empty_like(y_prob)

        groups = np.unique(sensitive_features)
        for group in groups:
            # Verify the group was present during fitting; otherwise the
            # calibrator would not know how to recalibrate these samples.
            if group not in self._calibrators:
                raise KeyError(
                    f"Group '{group}' was not seen during fit. "
                    f"Known groups: {list(self._calibrators.keys())}."
                )

            mask = sensitive_features == group
            probs_g = y_prob[mask]
            calibrator = self._calibrators[group]

            if self.method == "platt":
                # Apply the same log-odds transformation used during fit,
                # then use the fitted logistic regression to produce
                # calibrated probabilities.
                eps = 1e-8
                probs_clipped = np.clip(probs_g, eps, 1.0 - eps)
                X = np.log(probs_clipped / (1.0 - probs_clipped)).reshape(-1, 1)
                # predict_proba returns [P(Y=0), P(Y=1)]; we take column 1.
                calibrated[mask] = calibrator.predict_proba(X)[:, 1]
            else:
                # Isotonic regression: direct mapping from raw prob to
                # calibrated prob via the fitted step function.
                calibrated[mask] = calibrator.predict(probs_g)

        return calibrated

    def fit_transform(
        self,
        y_prob: np.ndarray,
        y_true: np.ndarray,
        sensitive_features: np.ndarray,
    ) -> np.ndarray:
        """Convenience method: fit then transform on the same data.

        Note that using the same data for fitting and transforming can lead
        to overfitting of the calibration model.  In practice, prefer using
        a held-out validation set for ``fit`` and a separate test set for
        ``transform``.

        Parameters
        ----------
        y_prob : array-like of shape (n_samples,)
            Raw predicted probabilities.
        y_true : array-like of shape (n_samples,)
            Binary ground-truth labels.
        sensitive_features : array-like of shape (n_samples,)
            Group membership.

        Returns
        -------
        calibrated : ndarray of shape (n_samples,)
            Calibrated probabilities.
        """
        self.fit(y_prob, y_true, sensitive_features)
        return self.transform(y_prob, sensitive_features)

    def __repr__(self):
        status = "fitted" if self._is_fitted else "not fitted"
        groups = list(self._calibrators.keys()) if self._is_fitted else []
        return (
            f"GroupFairnessCalibrator(method='{self.method}', "
            f"status='{status}', groups={groups})"
        )
