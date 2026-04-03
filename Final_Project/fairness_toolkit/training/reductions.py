"""Fairlearn ExponentiatedGradient wrapper with scikit-learn compatible interface.

This module wraps Fairlearn's ``ExponentiatedGradient`` algorithm behind a
simple fit/predict API that mirrors scikit-learn conventions, making it easy
to drop into existing ML workflows.

Mathematical Foundations
------------------------

**The Exponentiated Gradient (EG) Algorithm**

The EG algorithm (Agarwal et al., 2018) solves the constrained optimization
problem::

    minimize  L(h)
    subject to  C(h) <= eps

where L(h) is the classification loss of hypothesis h and C(h) is a
fairness constraint (e.g., demographic parity or equalized odds violation).

Rather than solving this constrained problem directly, EG reformulates it
as a min-max game between:
    1. A **Learner** that minimizes a cost-sensitive classification problem
       (weighted combination of accuracy loss and constraint violation).
    2. A **Auditor** that finds the group with the worst constraint
       violation and increases its Lagrange multiplier.

At each iteration t:
    - The auditor computes the current constraint violation and
      multiplicatively updates the dual variables (Lagrange multipliers)
      using exponentiated gradient ascent:
      lambda_{t+1} = lambda_t * exp(eta * violation_t)
    - The learner re-trains the base estimator on a reweighted dataset
      where sample weights reflect both the original loss and the
      fairness penalty imposed by the current multipliers.

The final model is a randomized mixture (convex combination) of all
the classifiers produced across iterations.

**Constraint Mapping**

Two standard fairness constraints are supported:

- ``demographic_parity``: Requires P(Y_hat=1 | G=g) to be approximately
  equal across all groups g. The ``difference_bound`` parameter (``eps``)
  sets the maximum allowed gap between any two groups' positive
  prediction rates.

- ``equalized_odds``: Requires P(Y_hat=1 | Y=y, G=g) to be approximately
  equal across groups, for each true label y in {0, 1}. This is a
  stronger condition that equalizes both true positive rates and false
  positive rates across groups.

References
----------
.. [1] Agarwal, A., Beygelzimer, A., Dudik, M., Langford, J., & Wallach, H.
       (2018). "A Reductions Approach to Fair Classification." ICML 2018.
"""

from __future__ import annotations

import numpy as np
from fairlearn.reductions import (
    ExponentiatedGradient,
    DemographicParity,
    EqualizedOdds,
)

# Registry that maps human-readable constraint names to Fairlearn constraint
# classes.  This pattern makes it straightforward to extend the wrapper with
# additional constraints (e.g., TruePositiveRateParity) in the future --
# simply add a new entry to this dictionary.
_CONSTRAINT_MAP = {
    "demographic_parity": DemographicParity,
    "equalized_odds": EqualizedOdds,
}


class ReductionsWrapper:
    """Scikit-learn compatible wrapper using Fairlearn's ExponentiatedGradient.

    Wraps a standard sklearn estimator to enforce fairness constraints during
    training via the exponentiated-gradient reduction approach.  The wrapper
    handles the translation between the sklearn API conventions and Fairlearn's
    ``sensitive_features`` requirement.

    Parameters
    ----------
    estimator : sklearn-compatible classifier
        Base learner (e.g., ``LogisticRegression``, ``XGBClassifier``).
        Must implement ``fit(X, y, sample_weight=...)`` and ``predict(X)``.
    constraint : str
        Fairness constraint to enforce.  One of ``'demographic_parity'`` or
        ``'equalized_odds'``.
    eps : float
        Maximum allowed constraint violation (tolerance).  Smaller values
        enforce stricter fairness but may reduce accuracy.  Typical values
        range from 0.01 to 0.05.

    Examples
    --------
    >>> from sklearn.linear_model import LogisticRegression
    >>> wrapper = ReductionsWrapper(LogisticRegression(), constraint='demographic_parity', eps=0.02)
    >>> wrapper.fit(X_train, y_train, sensitive_features=group_train)
    >>> preds = wrapper.predict(X_test)
    """

    def __init__(
        self,
        estimator,
        constraint: str = "demographic_parity",
        eps: float = 0.01,
    ):
        # Validate the constraint name early to give a clear error message
        # rather than failing deep inside Fairlearn.
        if constraint not in _CONSTRAINT_MAP:
            raise ValueError(
                f"Unknown constraint '{constraint}'. "
                f"Choose from {list(_CONSTRAINT_MAP.keys())}."
            )

        self.estimator = estimator
        self.constraint_name = constraint
        self.eps = eps

        # Instantiate the Fairlearn constraint object with the specified
        # tolerance.  ``difference_bound`` sets the maximum allowed gap
        # between the best-off and worst-off groups for the chosen metric.
        constraint_obj = _CONSTRAINT_MAP[constraint](difference_bound=eps)

        # Build the ExponentiatedGradient mitigator.  It will orchestrate
        # the iterative min-max game between learner and auditor during
        # ``fit()``.
        self._mitigator = ExponentiatedGradient(
            estimator=estimator,
            constraints=constraint_obj,
        )
        self._is_fitted = False

    def fit(self, X, y, sensitive_features):
        """Train the base estimator under the specified fairness constraint.

        Internally, this runs the exponentiated gradient algorithm: the base
        estimator is trained multiple times on reweighted versions of the
        data, and the final model is a randomized mixture of all iterations.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            Training features.
        y : array-like of shape (n_samples,)
            Binary target labels.
        sensitive_features : array-like of shape (n_samples,)
            Group membership for each sample (e.g., sex, race).

        Returns
        -------
        self : ReductionsWrapper
        """
        self._mitigator.fit(X, y, sensitive_features=sensitive_features)
        self._is_fitted = True
        return self

    def predict(self, X):
        """Return binary predictions from the mitigated model.

        The predictions come from the randomized mixture of classifiers
        produced during the EG training loop.  For a given input, each
        component classifier votes, and the final prediction is sampled
        (or thresholded) according to the mixture weights.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            Test features.

        Returns
        -------
        y_pred : ndarray of shape (n_samples,)
            Predicted binary labels.
        """
        self._check_is_fitted()
        return self._mitigator.predict(X)

    def predict_proba(self, X):
        """Return class-probability estimates if the base estimator supports it.

        Not all base estimators expose ``predict_proba`` (e.g., SVM with
        default settings). This method raises a clear error if the
        mitigated model cannot produce probabilities.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            Test features.

        Returns
        -------
        proba : ndarray of shape (n_samples, 2)
            Columns are [P(Y=0), P(Y=1)].
        """
        self._check_is_fitted()
        if not hasattr(self._mitigator, "predict_proba"):
            raise AttributeError(
                "The mitigated model does not support predict_proba. "
                "Ensure the base estimator exposes predict_proba."
            )
        return self._mitigator.predict_proba(X)

    def _check_is_fitted(self):
        """Guard method that prevents calling predict on an unfitted model."""
        if not self._is_fitted:
            raise RuntimeError(
                "This ReductionsWrapper instance is not fitted yet. "
                "Call .fit() before predict/predict_proba."
            )

    def __repr__(self):
        return (
            f"ReductionsWrapper(estimator={self.estimator!r}, "
            f"constraint='{self.constraint_name}', eps={self.eps})"
        )
