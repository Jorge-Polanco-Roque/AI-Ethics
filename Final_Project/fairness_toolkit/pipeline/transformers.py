"""Sklearn-compatible transformers for pre-processing bias mitigation.

This module provides two pre-processing transformers that can be plugged into
any scikit-learn ``Pipeline``:

* :class:`InstanceReweighter` -- computes per-sample weights that balance
  positive / negative outcomes across demographic groups.
* :class:`DisparateImpactRemover` -- repairs numeric features so that their
  distributions become less predictive of the sensitive attribute.

Mathematical Foundations
------------------------

**Instance Reweighting**

The key insight is that bias often manifests as an uneven distribution of
labels across demographic groups. Reweighting corrects this by assigning
higher weights to under-represented (group, label) combinations and lower
weights to over-represented ones.

For a sample belonging to demographic group *g* with label *l*, the weight
is computed as::

    w(g, l) = (n_g * n_l) / (N * n_{g,l})

where:
    - N       = total number of samples
    - n_g     = number of samples in group g
    - n_l     = number of samples with label l
    - n_{g,l} = number of samples in group g AND with label l

If group membership and label were statistically independent, we would
expect n_{g,l} = (n_g * n_l) / N. The weight is therefore the ratio of
this expected count to the observed count, i.e. w = E[n_{g,l}] / n_{g,l}.
Over-represented cells get w < 1 (down-weighted), under-represented cells
get w > 1 (up-weighted). This exactly counteracts the label imbalance
across groups.

**Disparate Impact Removal**

The repair mechanism shifts each group's feature distribution toward the
overall distribution by aligning their medians::

    X_repaired = X + repair_level * (overall_median - group_median)

A ``repair_level`` of 0.0 leaves the data untouched while 1.0 fully aligns
group medians, eliminating the median-level difference that a classifier
could exploit to proxy the sensitive attribute. Intermediate values
interpolate between the original and fully-repaired distributions, giving
the practitioner control over the accuracy-fairness trade-off.

References
----------
.. [1] Kamiran, F. & Calders, T. (2012). "Data preprocessing techniques
       for classification without discrimination." Knowledge and
       Information Systems, 33(1), 1-33.
.. [2] Feldman, M. et al. (2015). "Certifying and removing disparate
       impact." KDD 2015.
"""

from typing import Optional

import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin


class InstanceReweighter(BaseEstimator, TransformerMixin):
    """Compute sample weights to balance outcomes across demographic groups.

    The reweighting formula for a sample belonging to group *g* with label *l*
    is::

        w(g, l) = (n_g * n_l) / (N * n_{g,l})

    where *N* is the total number of samples, *n_g* the size of group *g*,
    *n_l* the number of samples with label *l*, and *n_{g,l}* the number of
    samples in group *g* that carry label *l*.

    After calling :meth:`fit`, per-sample weights are available in
    ``self.sample_weights_``.  :meth:`transform` returns *X* unchanged so that
    the transformer can be used inside a ``Pipeline``; downstream estimators
    should consume ``sample_weight_`` explicitly (e.g. via
    ``fit_params``).

    Parameters
    ----------
    sensitive_column_index : int, default=0
        Positional index of the sensitive-attribute column in *X*.
    """

    def __init__(self, sensitive_column_index: int = 0):
        self.sensitive_column_index = sensitive_column_index

    def fit(
        self,
        X: np.ndarray,
        y: Optional[np.ndarray] = None,
        sensitive_features: Optional[np.ndarray] = None,
    ) -> "InstanceReweighter":
        """Compute reweighting factors from group and label frequencies.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            Training data. Used to extract the sensitive attribute if
            ``sensitive_features`` is not provided.
        y : array-like of shape (n_samples,), optional
            Target labels. If None, all weights default to 1.0 (no
            reweighting), which makes the transformer a safe no-op in
            unsupervised pipelines.
        sensitive_features : array-like of shape (n_samples,), optional
            Explicit sensitive attribute vector. When provided, it takes
            precedence over extracting the column from *X*.

        Returns
        -------
        self : InstanceReweighter
            Fitted transformer with ``sample_weights_`` and ``weight_map_``
            attributes populated.
        """
        X = np.asarray(X)

        # Determine the sensitive attribute: prefer the explicit argument,
        # fall back to extracting the column from X by index.
        if sensitive_features is not None:
            sensitive = np.asarray(sensitive_features)
        else:
            sensitive = X[:, self.sensitive_column_index]

        # If no labels are provided, reweighting is meaningless -- assign
        # uniform weights so downstream code can proceed without errors.
        if y is None:
            self.sample_weights_ = np.ones(X.shape[0], dtype=np.float64)
            self.weight_map_ = {}
            return self

        y = np.asarray(y)
        n_total = len(y)

        # Identify all unique groups and labels to build the (group, label)
        # contingency table.
        groups = np.unique(sensitive)
        labels = np.unique(y)

        # Marginal counts: how many samples per group and per label.
        group_counts = {g: np.sum(sensitive == g) for g in groups}
        label_counts = {l: np.sum(y == l) for l in labels}

        # Joint counts: how many samples for each (group, label) cell.
        group_label_counts = {
            (g, l): np.sum((sensitive == g) & (y == l))
            for g in groups
            for l in labels
        }

        # Build the weight map.  Each (group, label) pair maps to a scalar
        # weight w(g,l) = (n_g * n_l) / (N * n_{g,l}).
        # Intuition: if label l is proportionally less common in group g
        # than in the population, those samples are up-weighted to
        # compensate.  An empty cell (n_{g,l}=0) receives weight 1.0 as
        # a safe default -- such samples do not exist, so the value is
        # irrelevant; it only guards against unseen combinations at
        # transform time.
        self.weight_map_: dict = {}
        weights = np.ones(n_total, dtype=np.float64)

        for g in groups:
            for l in labels:
                n_gl = group_label_counts[(g, l)]
                if n_gl == 0:
                    # No samples in this cell; assign neutral weight.
                    w = 1.0
                else:
                    # Core reweighting formula:
                    # w = E[n_{g,l}] / n_{g,l}  where  E[n_{g,l}] = n_g * n_l / N
                    w = (group_counts[g] * label_counts[l]) / (n_total * n_gl)
                self.weight_map_[(g, l)] = w

        # Vectorize: look up the weight for each sample's (group, label) pair.
        for i in range(n_total):
            key = (sensitive[i], y[i])
            weights[i] = self.weight_map_.get(key, 1.0)

        self.sample_weights_ = weights
        return self

    def transform(self, X: np.ndarray, y: Optional[np.ndarray] = None) -> np.ndarray:
        """Return *X* unchanged -- weights live in ``self.sample_weights_``.

        This pass-through design allows the transformer to sit in a
        sklearn Pipeline without altering the feature matrix.  The
        computed weights must be forwarded to the estimator's ``fit``
        method via ``sample_weight`` in ``fit_params``.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            Input data (returned as-is).
        y : ignored

        Returns
        -------
        X : ndarray of shape (n_samples, n_features)
        """
        return np.asarray(X)


class DisparateImpactRemover(BaseEstimator, TransformerMixin):
    """Reduce correlation between numeric features and a sensitive attribute.

    For every numeric feature the transformer computes the per-group median
    and the overall median, then shifts each group's values toward the overall
    median::

        X_repaired = X + repair_level * (overall_median - group_median)

    A ``repair_level`` of 0.0 leaves the data untouched while 1.0 fully
    aligns group medians. Intermediate values allow practitioners to trade
    off between data fidelity and fairness.

    Why medians?
    The median is chosen over the mean because it is robust to outliers and
    skewed distributions, which are common in real-world demographic data.
    Aligning medians removes the central tendency difference that a
    classifier could exploit as a proxy for the sensitive attribute.

    Parameters
    ----------
    sensitive_column_index : int, default=0
        Positional index of the sensitive-attribute column in *X*.
    repair_level : float, default=1.0
        Degree of repair in [0.0, 1.0].
    """

    def __init__(
        self, sensitive_column_index: int = 0, repair_level: float = 1.0
    ):
        self.sensitive_column_index = sensitive_column_index
        self.repair_level = repair_level

    def fit(
        self,
        X: np.ndarray,
        y: Optional[np.ndarray] = None,
        sensitive_features: Optional[np.ndarray] = None,
    ) -> "DisparateImpactRemover":
        """Learn group-conditional and overall medians for each feature.

        Only numeric features (all columns except the sensitive attribute
        column) are considered for repair.  The sensitive column itself is
        excluded because repairing it would destroy the group information.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            Training data (must be numeric).
        y : ignored
        sensitive_features : array-like of shape (n_samples,), optional
            Explicit sensitive attribute vector.

        Returns
        -------
        self : DisparateImpactRemover
            Fitted transformer with ``overall_medians_`` and
            ``group_medians_`` dictionaries populated.
        """
        X = np.asarray(X, dtype=np.float64)

        # Resolve the sensitive attribute vector.
        if sensitive_features is not None:
            sensitive = np.asarray(sensitive_features)
        else:
            sensitive = X[:, self.sensitive_column_index]

        # Store unique groups so transform() knows which groups to process.
        self.groups_ = np.unique(sensitive)
        n_features = X.shape[1]

        # Build the list of feature indices to repair -- everything except
        # the sensitive column itself.
        self.feature_indices_ = [
            j for j in range(n_features) if j != self.sensitive_column_index
        ]

        # For each repairable feature, compute:
        #   - overall_median: the median across all samples (the target)
        #   - group_median:   the median within each demographic group
        # The shift applied at transform time will be:
        #   repair_level * (overall_median - group_median)
        self.overall_medians_: dict = {}
        self.group_medians_: dict = {}

        for j in self.feature_indices_:
            col = X[:, j]
            # nanmedian handles potential NaN values gracefully.
            self.overall_medians_[j] = float(np.nanmedian(col))
            self.group_medians_[j] = {}
            for g in self.groups_:
                mask = sensitive == g
                group_vals = col[mask]
                if len(group_vals) == 0:
                    # If a group has no samples for this feature, default
                    # to the overall median so that the shift is zero.
                    self.group_medians_[j][g] = self.overall_medians_[j]
                else:
                    self.group_medians_[j][g] = float(np.nanmedian(group_vals))

        # Store the fitted sensitive vector (not strictly needed for
        # transform, but useful for diagnostics).
        self._sensitive_fit = sensitive
        return self

    def transform(
        self,
        X: np.ndarray,
        y: Optional[np.ndarray] = None,
        sensitive_features: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Apply the median-shift repair to numeric features.

        For each feature j and each demographic group g, the repair is::

            X[group_mask, j] += repair_level * (overall_median_j - group_median_j)

        This additive shift moves each group's distribution toward the
        overall median while preserving within-group variance and rank
        ordering.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            Data to transform.
        y : ignored
        sensitive_features : array-like of shape (n_samples,), optional
            Sensitive attribute vector for the transform data.

        Returns
        -------
        X_repaired : ndarray of shape (n_samples, n_features)
            Repaired copy of *X* (the original is not modified).
        """
        # Create an explicit copy so the original data is never mutated.
        X = np.array(X, dtype=np.float64, copy=True)

        # Resolve the sensitive attribute for the transform data.
        if sensitive_features is not None:
            sensitive = np.asarray(sensitive_features)
        else:
            sensitive = X[:, self.sensitive_column_index]

        # Apply the additive median-shift repair to each (feature, group)
        # combination.
        for j in self.feature_indices_:
            overall_med = self.overall_medians_[j]
            for g in self.groups_:
                mask = sensitive == g
                if not np.any(mask):
                    # Group not present in this data split; skip to avoid
                    # unnecessary computation.
                    continue
                group_med = self.group_medians_[j].get(g, overall_med)
                # The shift is proportional to repair_level:
                #   - repair_level=0  =>  shift=0         (no change)
                #   - repair_level=1  =>  shift=full gap  (complete alignment)
                shift = self.repair_level * (overall_med - group_med)
                X[mask, j] += shift

        return X
