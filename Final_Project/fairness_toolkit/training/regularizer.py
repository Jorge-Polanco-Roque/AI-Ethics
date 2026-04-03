"""PyTorch fairness-regularized loss function.

This module implements a composite loss function that jointly optimizes for
predictive accuracy and demographic fairness. It is designed for use in
PyTorch training loops where a neural network (or any differentiable model)
produces raw logits.

Mathematical Foundations
------------------------

**Loss Formulation**

The total loss combines two terms::

    L_total = L_BCE(logits, targets) + eta * L_fairness

where:
    - L_BCE is the standard binary cross-entropy with logits:
      L_BCE = -1/N * sum[ t_i * log(sigma(z_i)) + (1 - t_i) * log(1 - sigma(z_i)) ]
      with sigma(z) = 1 / (1 + exp(-z)) being the sigmoid function.

    - L_fairness is a squared-difference demographic parity penalty:
      L_fairness = ( E[sigma(z) | G=0] - E[sigma(z) | G=1] )^2

    - eta >= 0 is the regularization strength that controls the
      accuracy-fairness trade-off. When eta=0, the loss reduces to
      pure BCE; as eta grows, the model is increasingly penalized for
      producing different average predictions across the two groups.

**Why Squared Difference?**

The squared difference (rather than absolute difference) is chosen because:
    1. It is everywhere differentiable, ensuring smooth gradient flow for
       backpropagation (no subgradient issues at zero).
    2. It penalizes large violations quadratically, providing stronger
       incentive to reduce large gaps than small ones.

**Gradient Flow Design**

Every operation in the forward pass is differentiable with respect to
the model parameters:
    - ``torch.sigmoid`` is smooth and has well-behaved gradients.
    - Boolean masking preserves gradient flow to the selected elements.
    - ``mean()`` over a subset of predictions produces gradients that
      flow back only to those predictions' logits.

When one of the two groups is absent from a mini-batch (e.g., due to
small batch sizes or severe class imbalance), the fairness penalty is
set to zero with ``requires_grad=False`` to avoid polluting the
gradient computation with undefined group statistics.

References
----------
.. [1] Beutel, A., Chen, J., Zhao, Z., & Chi, E.H. (2017). "Data
       Decisions and Theoretical Implications when Adversarially
       Learning Fair Representations." FAT/ML Workshop.
.. [2] Kamishima, T., Akaho, S., Asoh, H., & Sakuma, J. (2012).
       "Fairness-Aware Classifier with Prejudice Remover Regularizer."
       ECML-PKDD 2012.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class FairnessRegularizer(nn.Module):
    """PyTorch loss that adds a fairness penalty to standard BCE loss.

    The total loss is computed as::

        Loss = BCEWithLogitsLoss(logits, targets) + eta * fairness_penalty

    where ``fairness_penalty`` is the squared difference in mean predicted
    probability between the two demographic groups::

        fairness_penalty = (mean_sigmoid(logits[group==0]) - mean_sigmoid(logits[group==1]))^2

    Parameters
    ----------
    eta : float
        Weight of the fairness penalty term.  ``eta=0`` recovers pure BCE.
        Typical values range from 0.1 (mild fairness nudge) to 10.0
        (strong fairness enforcement).

    Examples
    --------
    >>> criterion = FairnessRegularizer(eta=1.5)
    >>> total, bce, penalty = criterion(logits, targets, sensitive)
    >>> total.backward()
    """

    def __init__(self, eta: float = 1.0):
        super().__init__()
        self.eta = eta
        # BCEWithLogitsLoss combines sigmoid + BCE in a single numerically
        # stable operation (uses the log-sum-exp trick internally to avoid
        # overflow/underflow in the log(sigmoid(z)) computation).
        self.bce = nn.BCEWithLogitsLoss()

    def forward(
        self,
        logits: torch.Tensor,
        targets: torch.Tensor,
        sensitive_features: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Compute the combined accuracy + fairness loss.

        The method returns all three components (total, accuracy, penalty)
        separately so that training loops can log them independently for
        monitoring the accuracy-fairness trade-off over epochs.

        Parameters
        ----------
        logits : Tensor of shape (N,)
            Raw model output (before sigmoid).
        targets : Tensor of shape (N,)
            Binary ground-truth labels (0 or 1), float dtype.
        sensitive_features : Tensor of shape (N,)
            Binary group indicator (0 or 1).

        Returns
        -------
        total_loss : Tensor (scalar)
            BCE + eta * fairness_penalty.
        accuracy_loss : Tensor (scalar)
            The pure BCE component.
        fairness_penalty : Tensor (scalar)
            The squared group-mean-prediction difference.
        """
        # --- Accuracy term ---
        # Standard binary cross-entropy with logits (numerically stable).
        accuracy_loss = self.bce(logits, targets)

        # --- Fairness penalty term ---
        # Convert logits to probabilities via sigmoid.  We apply sigmoid
        # explicitly (rather than relying on BCEWithLogitsLoss) because we
        # need the predicted probabilities to compute group-wise means.
        probs = torch.sigmoid(logits)

        # Create boolean masks for each demographic group.
        mask_0 = sensitive_features == 0
        mask_1 = sensitive_features == 1

        if mask_0.any() and mask_1.any():
            # Compute the mean predicted probability for each group.
            # These means approximate E[P(Y=1 | X) | G=g], the expected
            # positive prediction rate conditioned on group membership.
            mean_0 = probs[mask_0].mean()
            mean_1 = probs[mask_1].mean()

            # Squared difference: penalizes demographic parity violations.
            # The gradient w.r.t. logits[i] for a sample in group 0 is:
            #   d(penalty)/d(z_i) = 2*(mean_0 - mean_1) * sigma'(z_i) / n_0
            # This pushes group 0's predictions toward group 1's mean
            # (and vice versa), equalizing the positive rates.
            fairness_penalty = (mean_0 - mean_1) ** 2
        else:
            # If only one group is present in the batch (or a group is
            # empty), the fairness penalty is undefined -- we cannot
            # compare two groups if one is missing.  Setting
            # requires_grad=False ensures no spurious gradients.
            fairness_penalty = torch.tensor(0.0, device=logits.device, requires_grad=False)

        # --- Combined loss ---
        # The eta hyperparameter controls the trade-off:
        #   eta=0   => pure accuracy optimization (ignore fairness)
        #   eta>>1  => fairness dominates (may sacrifice accuracy)
        total_loss = accuracy_loss + self.eta * fairness_penalty

        return total_loss, accuracy_loss, fairness_penalty

    def __repr__(self):
        return f"FairnessRegularizer(eta={self.eta})"
