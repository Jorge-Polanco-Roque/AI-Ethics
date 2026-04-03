"""
Core fairness metrics for classification and regression models.

Mathematical Foundations
------------------------
Fairness metrics quantify whether a model's predictions exhibit systematic
disparities across demographic groups defined by one or more sensitive
(protected) features such as sex, race, or age.

This module implements three widely used group-fairness criteria:

1. **Demographic Parity** (also called Statistical Parity or Independence):
   A classifier satisfies demographic parity when the probability of
   receiving a positive prediction is independent of group membership:

       P(Y_hat = 1 | G = a) = P(Y_hat = 1 | G = b)   for all groups a, b

   The *demographic parity difference* is the maximum absolute gap in
   positive-prediction rates across all pairs of groups.

2. **Equalized Odds** (also called Separation):
   A classifier satisfies equalized odds when the true-positive rate (TPR)
   and the false-positive rate (FPR) are equal across groups, conditioned
   on the true label:

       P(Y_hat = 1 | Y = y, G = a) = P(Y_hat = 1 | Y = y, G = b)
       for y in {0, 1} and all groups a, b

   The *equalized odds difference* is max(TPR_disparity, FPR_disparity),
   capturing the worst-case conditional rate gap.

3. **Regression Fairness (MAE-based)**:
   For continuous predictions, fairness can be measured by requiring that
   the model's mean absolute error (MAE) is consistent across groups:

       MAE_a ~= MAE_b   for all groups a, b

   The metric reports the maximum absolute pairwise difference in per-group
   MAE values.

Multi-group Handling
--------------------
When more than two groups exist, computing a single disparity number
requires a reduction strategy.  This module uses the **maximum pairwise
disparity** approach: for k groups there are C(k, 2) = k*(k-1)/2 pairs,
and we report the largest absolute difference.  This is the worst-case
(most conservative) summary and is the same convention used by Fairlearn's
``MetricFrame.difference()`` method.
"""

from itertools import combinations
from typing import Union

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_arrays(
    *args: Union[np.ndarray, pd.Series, list],
) -> list[np.ndarray]:
    """Convert heterogeneous inputs to flat 1-D numpy arrays and validate shapes.

    Parameters
    ----------
    *args : array-like
        One or more inputs that can be numpy arrays, pandas Series, or
        plain Python lists.

    Returns
    -------
    list of np.ndarray
        Each input converted to a 1-D numpy array.

    Raises
    ------
    ValueError
        If the resulting arrays have mismatched lengths.
    """
    # np.asarray handles Series, lists, and ndarrays uniformly;
    # .ravel() guarantees 1-D even if a column vector is passed.
    arrays = [np.asarray(a).ravel() for a in args]

    # All arrays must describe the same set of samples.
    lengths = {len(a) for a in arrays}
    if len(lengths) != 1:
        raise ValueError(
            f"All input arrays must have the same length; got lengths {lengths}"
        )
    return arrays


def _group_labels(sensitive_features: np.ndarray) -> list:
    """Return sorted unique group labels from a sensitive-feature vector.

    Parameters
    ----------
    sensitive_features : np.ndarray
        1-D array of group membership indicators (e.g. ['M', 'F', 'M']).

    Returns
    -------
    list
        Sorted list of unique group labels.  Sorting ensures deterministic
        iteration order regardless of the input ordering.
    """
    return sorted(np.unique(sensitive_features).tolist())


def _max_pairwise_disparity(per_group_values: dict[str, float]) -> float:
    """Return the maximum absolute difference across all group pairs.

    Given k groups with scalar metric values {v_1, ..., v_k}, this function
    computes:

        max_{(i, j) in C(k,2)} |v_i - v_j|

    where C(k, 2) denotes all 2-combinations of the k groups.  This is the
    worst-case (most conservative) summary of inter-group disparity.

    Parameters
    ----------
    per_group_values : dict
        Mapping of group label -> scalar metric value.

    Returns
    -------
    float
        Maximum absolute pairwise difference.  Returns 0.0 if fewer than
        two groups are present (no pair to compare).
    """
    labels = list(per_group_values.keys())

    # With 0 or 1 groups there is no pair to compare.
    if len(labels) < 2:
        return 0.0

    # Enumerate all C(k,2) pairs and take the maximum absolute difference.
    return max(
        abs(per_group_values[a] - per_group_values[b])
        for a, b in combinations(labels, 2)
    )


# ---------------------------------------------------------------------------
# Public metrics
# ---------------------------------------------------------------------------

def demographic_parity_difference(
    y_pred: Union[np.ndarray, pd.Series, list],
    sensitive_features: Union[np.ndarray, pd.Series, list],
) -> float:
    """Compute the demographic parity difference (selection-rate gap).

    For each group defined by *sensitive_features*, the positive prediction
    rate P(Y_hat = 1 | group) is calculated as the arithmetic mean of the
    predicted labels within that group.  The metric is the maximum absolute
    difference of those rates across all group pairs:

        DPD = max_{(a,b)} | mean(y_pred[G=a]) - mean(y_pred[G=b]) |

    A value of 0 indicates perfect demographic parity -- all groups receive
    positive predictions at exactly the same rate.

    Parameters
    ----------
    y_pred : array-like of shape (n_samples,)
        Predicted labels (binary 0/1 or boolean).
    sensitive_features : array-like of shape (n_samples,)
        Group membership for each sample.

    Returns
    -------
    float
        Maximum absolute difference in positive prediction rates.

    Examples
    --------
    >>> demographic_parity_difference([1, 0, 1, 0], ['A', 'A', 'B', 'B'])
    0.0
    """
    y_pred, sensitive_features = _to_arrays(y_pred, sensitive_features)

    groups = _group_labels(sensitive_features)

    # Compute the positive-prediction rate (selection rate) for each group.
    # For binary predictions, np.mean gives P(Y_hat = 1 | G = g).
    rates: dict[str, float] = {}
    for g in groups:
        mask = sensitive_features == g
        rates[g] = float(np.mean(y_pred[mask]))

    # Return the worst-case gap across all pairs.
    return _max_pairwise_disparity(rates)


def equalized_odds_difference(
    y_true: Union[np.ndarray, pd.Series, list],
    y_pred: Union[np.ndarray, pd.Series, list],
    sensitive_features: Union[np.ndarray, pd.Series, list],
) -> float:
    """Compute the equalized odds difference.

    Equalized odds requires that both the true-positive rate (TPR) and the
    false-positive rate (FPR) are equal across groups.  Formally:

        TPR_g = P(Y_hat = 1 | Y = 1, G = g)   -- sensitivity per group
        FPR_g = P(Y_hat = 1 | Y = 0, G = g)   -- fall-out per group

    This metric returns the larger of the two worst-case pairwise gaps:

        EOD = max( max_{(a,b)} |TPR_a - TPR_b|,
                   max_{(a,b)} |FPR_a - FPR_b| )

    A value of 0 means the classifier's error rates are perfectly balanced
    across groups for both positive and negative ground-truth classes.

    Parameters
    ----------
    y_true : array-like of shape (n_samples,)
        Ground-truth labels (binary 0/1).
    y_pred : array-like of shape (n_samples,)
        Predicted labels (binary 0/1).
    sensitive_features : array-like of shape (n_samples,)
        Group membership for each sample.

    Returns
    -------
    float
        Maximum of TPR disparity and FPR disparity.
    """
    y_true, y_pred, sensitive_features = _to_arrays(
        y_true, y_pred, sensitive_features
    )

    groups = _group_labels(sensitive_features)
    tpr_per_group: dict[str, float] = {}
    fpr_per_group: dict[str, float] = {}

    for g in groups:
        mask = sensitive_features == g
        yt = y_true[mask]
        yp = y_pred[mask]

        # Boolean masks for the actual positive and negative samples
        # within this group.
        positives = yt == 1
        negatives = yt == 0

        # TPR = TP / (TP + FN) = mean(y_pred) among actual positives.
        # If a group has no actual positives, TPR is undefined; we default
        # to 0.0 so the group does not inflate the disparity artificially.
        if positives.sum() > 0:
            tpr_per_group[g] = float(np.mean(yp[positives]))
        else:
            tpr_per_group[g] = 0.0

        # FPR = FP / (FP + TN) = mean(y_pred) among actual negatives.
        # Same edge-case handling as TPR above.
        if negatives.sum() > 0:
            fpr_per_group[g] = float(np.mean(yp[negatives]))
        else:
            fpr_per_group[g] = 0.0

    # Compute worst-case pairwise disparity for each conditional rate.
    tpr_disparity = _max_pairwise_disparity(tpr_per_group)
    fpr_disparity = _max_pairwise_disparity(fpr_per_group)

    # The equalized odds criterion requires BOTH rates to be equal, so
    # we report the larger of the two gaps as the single summary statistic.
    return max(tpr_disparity, fpr_disparity)


def regression_fairness_mae(
    y_true: Union[np.ndarray, pd.Series, list],
    y_pred: Union[np.ndarray, pd.Series, list],
    sensitive_features: Union[np.ndarray, pd.Series, list],
) -> float:
    """Compute the maximum pairwise difference in MAE across groups.

    For regression tasks, fairness can be assessed by checking whether the
    model's prediction error is consistent across demographic groups.
    The per-group Mean Absolute Error is:

        MAE_g = (1 / n_g) * sum_{i in G=g} |y_true_i - y_pred_i|

    The metric reports the worst-case gap:

        RF_MAE = max_{(a,b)} |MAE_a - MAE_b|

    A value of 0 means the model errs equally (in absolute terms) for all
    groups.  Large values indicate that some groups bear disproportionately
    higher prediction error.

    Parameters
    ----------
    y_true : array-like of shape (n_samples,)
        Ground-truth continuous target values.
    y_pred : array-like of shape (n_samples,)
        Predicted continuous target values.
    sensitive_features : array-like of shape (n_samples,)
        Group membership for each sample.

    Returns
    -------
    float
        Maximum absolute difference in per-group MAE.
    """
    y_true, y_pred, sensitive_features = _to_arrays(
        y_true, y_pred, sensitive_features
    )

    groups = _group_labels(sensitive_features)
    mae_per_group: dict[str, float] = {}

    for g in groups:
        mask = sensitive_features == g
        # MAE for this group: average of element-wise absolute residuals.
        mae_per_group[g] = float(np.mean(np.abs(y_true[mask] - y_pred[mask])))

    return _max_pairwise_disparity(mae_per_group)
