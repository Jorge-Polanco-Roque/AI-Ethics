"""
Bias detection engine for auditing datasets across multiple fairness dimensions.

This module provides ``BiasDetectionEngine``, a stateless auditor that runs
a battery of statistical tests on a pandas DataFrame to surface three
complementary categories of data bias:

1. **Representation bias** -- Are demographic groups under- or
   over-represented relative to a known (or assumed-uniform) reference
   distribution?  Tested via a chi-squared goodness-of-fit test.

2. **Statistical disparity** -- Do feature distributions differ
   significantly across sensitive groups?  Continuous features are tested
   with pairwise two-sample Kolmogorov-Smirnov (KS) tests; categorical
   features with chi-squared tests of independence.

3. **Proxy variables** -- Are any features highly correlated with the
   protected attribute, potentially re-encoding it indirectly?  Pearson
   correlation is used for numeric features and Cramer's V for categorical
   ones.

The engine is designed for *pre-training* auditing: you run it on the raw
dataset before any model is involved, so that pipeline engineers can
identify and address data-level issues early.

All results are returned as plain dicts (JSON-serialisable via the helper
``save_report``) so they can be consumed by downstream tooling, logged to
MLflow, or rendered in a notebook.
"""

import json
import warnings
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, chisquare, ks_2samp, pearsonr


# ---------------------------------------------------------------------------
# Helper: Cramer's V
# ---------------------------------------------------------------------------

def _cramers_v(confusion_matrix: np.ndarray) -> float:
    """Compute Cramer's V statistic for a contingency table.

    Cramer's V quantifies the strength of association between two
    categorical variables.  It is derived from the chi-squared statistic
    of the contingency table and is normalised to the range [0, 1]:

        V = sqrt( chi2 / (n * min(r-1, k-1)) )

    where *n* is the total count and *r*, *k* are the number of rows
    and columns respectively.  A value of 0 means no association;
    1 means perfect association.

    Parameters
    ----------
    confusion_matrix : np.ndarray
        A 2-D array of observed counts (contingency table).

    Returns
    -------
    float
        Cramer's V value, clamped to 0.0 when the table is degenerate
        (single row/column or zero total count).
    """
    # Obtain the chi-squared statistic from scipy; we discard the
    # p-value, degrees of freedom, and expected frequencies.
    chi2, _, _, _ = chi2_contingency(confusion_matrix)
    n = confusion_matrix.sum()
    r, k = confusion_matrix.shape

    # min_dim is min(r, k) - 1.  If either dimension is 1 (or the table
    # is empty), Cramer's V is undefined -- return 0 by convention.
    min_dim = min(r, k) - 1
    if min_dim == 0 or n == 0:
        return 0.0

    return float(np.sqrt(chi2 / (n * min_dim)))


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class BiasDetectionEngine:
    """Audits raw data for bias across multiple dimensions.

    This engine runs a suite of statistical tests to identify
    representation bias, statistical disparity across groups, and proxy
    variables that may encode protected attributes indirectly.

    Parameters
    ----------
    sensitive_column : str
        Name of the protected-attribute column in the DataFrames that
        will be passed to the detection methods.
    reference_distribution : dict or None, optional
        Expected group proportions keyed by group label.  When ``None``
        (the default), a uniform distribution over the observed groups
        is assumed -- i.e., every group is expected to appear with equal
        frequency.
    significance_level : float, default 0.05
        P-value threshold below which a statistical test result is
        declared significant.  Used consistently across all tests
        (chi-squared, KS, etc.).

    Attributes
    ----------
    sensitive_column : str
    reference_distribution : dict or None
    significance_level : float
    """

    def __init__(
        self,
        sensitive_column: str,
        reference_distribution: Optional[dict] = None,
        significance_level: float = 0.05,
    ):
        self.sensitive_column = sensitive_column
        self.reference_distribution = reference_distribution
        self.significance_level = significance_level

    # ------------------------------------------------------------------
    # Representation bias
    # ------------------------------------------------------------------

    def detect_representation_bias(self, df: pd.DataFrame) -> dict:
        """Compare observed group proportions against a reference distribution.

        A chi-squared goodness-of-fit test (``scipy.stats.chisquare``) is
        used to determine whether the observed group frequencies differ
        significantly from the expected frequencies.

        Parameters
        ----------
        df : pd.DataFrame
            The dataset to audit.  Must contain ``self.sensitive_column``.

        Returns
        -------
        dict
            Keys: ``group_counts``, ``group_proportions``,
            ``expected_proportions``, ``chi2_statistic``, ``p_value``,
            ``is_biased``.
        """
        self._validate_column(df, self.sensitive_column)

        # Count how many samples belong to each demographic group.
        counts = df[self.sensitive_column].value_counts()
        total = counts.sum()
        groups = counts.index.tolist()
        proportions = (counts / total).to_dict()

        # If the caller did not supply an explicit reference distribution,
        # fall back to uniform: each group is expected to have equal share.
        if self.reference_distribution is not None:
            ref = self.reference_distribution
        else:
            ref = {g: 1.0 / len(groups) for g in groups}

        # Convert proportions to expected counts so that the chi-squared
        # test operates on the same scale as the observed counts.
        expected_counts = np.array([ref.get(g, 0) * total for g in groups])
        observed_counts = np.array([counts[g] for g in groups])

        # Zero expected counts make the chi-squared statistic blow up to
        # infinity; warn the user so the result is not silently misleading.
        if np.any(expected_counts == 0):
            warnings.warn(
                "Some expected counts are zero; chi-squared test may be unreliable.",
                UserWarning,
            )

        # scipy.stats.chisquare performs the one-way chi-squared
        # goodness-of-fit test: H0 = observed counts match expected counts.
        chi2_stat, p_value = chisquare(f_obs=observed_counts, f_exp=expected_counts)

        return {
            "group_counts": counts.to_dict(),
            "group_proportions": proportions,
            "expected_proportions": {g: ref.get(g, 0) for g in groups},
            "chi2_statistic": float(chi2_stat),
            "p_value": float(p_value),
            # Declare bias if p < significance_level (reject H0).
            "is_biased": bool(p_value < self.significance_level),
        }

    # ------------------------------------------------------------------
    # Statistical disparity
    # ------------------------------------------------------------------

    def detect_statistical_disparity(
        self, df: pd.DataFrame, target_column: str
    ) -> dict:
        """Test whether feature distributions differ across sensitive groups.

        For every column in ``df`` (excluding the sensitive column and the
        target), this method selects the appropriate test based on dtype:

        * **Numeric features** -- pairwise two-sample Kolmogorov-Smirnov
          tests across all pairs of demographic groups.  Only the worst-case
          (maximum statistic) pair is reported.
        * **Categorical features** -- chi-squared test of independence
          between the feature and the sensitive column.

        Parameters
        ----------
        df : pd.DataFrame
            The dataset to audit.
        target_column : str
            The prediction target column; excluded from testing.

        Returns
        -------
        dict
            Mapping from feature name to a result dict containing
            ``statistic``, ``p_value``, ``test_used``, and
            ``is_significant``.
        """
        self._validate_column(df, self.sensitive_column)
        self._validate_column(df, target_column)

        groups = df[self.sensitive_column].unique()

        # Exclude the sensitive attribute and the target -- we only want
        # to test the regular feature columns for distributional shifts.
        features = [
            c for c in df.columns if c not in (self.sensitive_column, target_column)
        ]

        results: dict = {}
        for feature in features:
            if pd.api.types.is_numeric_dtype(df[feature]):
                # Continuous feature: use KS test to compare CDFs.
                results[feature] = self._ks_test_across_groups(df, feature, groups)
            else:
                # Categorical feature: use chi-squared independence test.
                results[feature] = self._chi2_test_across_groups(df, feature)

        return results

    def _ks_test_across_groups(
        self, df: pd.DataFrame, feature: str, groups: np.ndarray
    ) -> dict:
        """Run pairwise two-sample KS tests and report the worst-case pair.

        The Kolmogorov-Smirnov test compares the empirical CDFs of two
        samples.  A large test statistic (and correspondingly small
        p-value) indicates that the two groups have significantly
        different distributions for the given feature.

        We test every unique pair of groups and keep only the pair with
        the largest KS statistic ("worst-case") because if *any* pair
        shows a significant difference the feature is potentially biased.

        Parameters
        ----------
        df : pd.DataFrame
            Full dataset.
        feature : str
            The numeric column to test.
        groups : np.ndarray
            Unique values of the sensitive column.

        Returns
        -------
        dict
            ``statistic``, ``p_value``, ``test_used``, ``is_significant``.
        """
        max_stat = 0.0
        min_p = 1.0

        # Enumerate all unique pairs of groups (i < j avoids duplicates).
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                # Extract feature values for each group, dropping NaNs
                # because the KS test cannot handle missing data.
                vals_i = df.loc[df[self.sensitive_column] == groups[i], feature].dropna()
                vals_j = df.loc[df[self.sensitive_column] == groups[j], feature].dropna()

                # Need at least 2 observations per group for the KS test
                # to produce a meaningful result.
                if len(vals_i) < 2 or len(vals_j) < 2:
                    continue

                stat, p = ks_2samp(vals_i, vals_j)

                # Track the worst-case pair: highest statistic wins.
                if stat > max_stat:
                    max_stat = stat
                    min_p = p

        return {
            "statistic": float(max_stat),
            "p_value": float(min_p),
            "test_used": "ks",
            "is_significant": bool(min_p < self.significance_level),
        }

    def _chi2_test_across_groups(self, df: pd.DataFrame, feature: str) -> dict:
        """Chi-squared test of independence between a feature and the sensitive column.

        Builds a contingency table (sensitive_column x feature) and runs
        ``scipy.stats.chi2_contingency``.  The null hypothesis is that
        the two variables are independent -- rejection means the feature
        distribution depends on the sensitive attribute.

        Parameters
        ----------
        df : pd.DataFrame
            Full dataset.
        feature : str
            The categorical column to test.

        Returns
        -------
        dict
            ``statistic``, ``p_value``, ``test_used``, ``is_significant``.
        """
        contingency = pd.crosstab(df[self.sensitive_column], df[feature])

        # A contingency table with fewer than 2 rows or 2 columns is
        # trivially non-informative (no variation in at least one variable),
        # so we return a null result instead of letting scipy raise.
        if contingency.shape[0] < 2 or contingency.shape[1] < 2:
            return {
                "statistic": 0.0,
                "p_value": 1.0,
                "test_used": "chi2",
                "is_significant": False,
            }

        chi2, p, _, _ = chi2_contingency(contingency.values)
        return {
            "statistic": float(chi2),
            "p_value": float(p),
            "test_used": "chi2",
            "is_significant": bool(p < self.significance_level),
        }

    # ------------------------------------------------------------------
    # Proxy variable detection
    # ------------------------------------------------------------------

    def detect_proxy_variables(
        self, df: pd.DataFrame, threshold: float = 0.3
    ) -> dict:
        """Identify features highly correlated with the sensitive attribute.

        A "proxy variable" is a feature that, while not explicitly a
        protected attribute, carries enough information about it to let
        a model reconstruct the protected attribute indirectly (e.g.,
        zip code as a proxy for race).

        For **numeric features**, the absolute Pearson correlation
        coefficient with the integer-encoded sensitive column is used.
        For **categorical features**, Cramer's V is used instead because
        Pearson correlation is not meaningful for unordered categories.

        Parameters
        ----------
        df : pd.DataFrame
            The dataset to audit.
        threshold : float, default 0.3
            Minimum correlation (Pearson or Cramer's V) above which a
            feature is flagged as a potential proxy.  The default of 0.3
            corresponds to a "moderate" association in most effect-size
            guidelines.

        Returns
        -------
        dict
            Mapping from feature name to a dict with ``correlation``,
            ``method`` (``'pearson'`` or ``'cramers_v'``), and
            ``is_proxy`` (bool).
        """
        self._validate_column(df, self.sensitive_column)

        # Encode the sensitive column as integer codes so we can compute
        # Pearson correlation with numeric features.  The ordering is
        # arbitrary (alphabetical by default) but consistent.
        sensitive_encoded = df[self.sensitive_column].astype("category").cat.codes

        # Test every column except the sensitive attribute itself.
        features = [c for c in df.columns if c != self.sensitive_column]
        results: dict = {}

        for feature in features:
            if pd.api.types.is_numeric_dtype(df[feature]):
                # --- Numeric feature: Pearson correlation ----------------
                # Create a temporary DataFrame with the feature and the
                # encoded sensitive column, then drop rows with NaNs so
                # pearsonr receives clean arrays.
                clean = df[[feature]].assign(_sens=sensitive_encoded).dropna()

                if len(clean) < 3:
                    # pearsonr requires at least 3 data points to produce
                    # a meaningful result; with fewer we cannot estimate
                    # correlation reliably.
                    corr_val = 0.0
                else:
                    corr_val, _ = pearsonr(clean[feature], clean["_sens"])
                    # We care about magnitude, not direction, because a
                    # strong negative correlation is equally problematic.
                    corr_val = abs(float(corr_val))

                results[feature] = {
                    "correlation": corr_val,
                    "method": "pearson",
                    "is_proxy": bool(corr_val >= threshold),
                }
            else:
                # --- Categorical feature: Cramer's V ---------------------
                # Build a contingency table and compute the association
                # strength.  Cramer's V is already in [0, 1] and unsigned.
                contingency = pd.crosstab(df[self.sensitive_column], df[feature])
                v = _cramers_v(contingency.values)

                results[feature] = {
                    "correlation": float(v),
                    "method": "cramers_v",
                    "is_proxy": bool(v >= threshold),
                }

        return results

    # ------------------------------------------------------------------
    # Full audit
    # ------------------------------------------------------------------

    def full_audit(
        self, df: pd.DataFrame, target_column: Optional[str] = None
    ) -> dict:
        """Run all available detection methods and compile a comprehensive report.

        This is the main entry point for a complete dataset audit.  It
        always runs representation bias and proxy variable detection.
        Statistical disparity detection is included only when
        ``target_column`` is provided (because the engine needs to know
        which column to exclude from testing).

        Parameters
        ----------
        df : pd.DataFrame
            The dataset to audit.
        target_column : str or None, optional
            Name of the prediction target column.  When provided,
            statistical disparity detection is included in the report.

        Returns
        -------
        dict
            A nested dictionary with keys ``representation_bias``,
            ``proxy_variables``, optionally ``statistical_disparity``,
            and a ``summary`` dict that aggregates the key findings.
        """
        report: dict = {}

        # Phase 1: check whether demographic groups are proportionally
        # represented in the dataset.
        report["representation_bias"] = self.detect_representation_bias(df)

        # Phase 2: identify features that may act as proxies for the
        # protected attribute.
        report["proxy_variables"] = self.detect_proxy_variables(df)

        # Phase 3 (optional): test each feature's distribution for
        # significant differences across groups.
        if target_column is not None:
            report["statistical_disparity"] = self.detect_statistical_disparity(
                df, target_column
            )

        # Summarise the audit into a quick-glance overview so consumers
        # can decide at a glance whether deeper investigation is needed.
        proxy_count = sum(
            1 for v in report["proxy_variables"].values() if v["is_proxy"]
        )
        disparity_count = 0
        if "statistical_disparity" in report:
            disparity_count = sum(
                1
                for v in report["statistical_disparity"].values()
                if v["is_significant"]
            )

        report["summary"] = {
            "has_representation_bias": report["representation_bias"]["is_biased"],
            "proxy_count": proxy_count,
            "significant_disparity_count": disparity_count,
        }

        return report

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, report: dict, path: str) -> None:
        """Save an audit report to disk as a JSON file.

        Numpy scalar types (``np.int64``, ``np.float64``, ``np.bool_``,
        etc.) are not natively JSON-serialisable.  A custom ``default``
        handler converts them to Python built-ins so that ``json.dump``
        succeeds without requiring the caller to pre-process the report.

        Parameters
        ----------
        report : dict
            The audit report dictionary (e.g., from ``full_audit``).
        path : str
            Destination file path.
        """
        def _convert(obj):
            """Fallback serialiser for numpy types."""
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=_convert)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_column(df: pd.DataFrame, column: str) -> None:
        """Raise a clear error if a required column is missing from the DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            The DataFrame to check.
        column : str
            The column name that must be present.

        Raises
        ------
        ValueError
            If ``column`` is not in ``df.columns``.
        """
        if column not in df.columns:
            raise ValueError(
                f"Column '{column}' not found in DataFrame. "
                f"Available columns: {list(df.columns)}"
            )
