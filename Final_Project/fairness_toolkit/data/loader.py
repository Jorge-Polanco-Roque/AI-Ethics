"""
Data loading utilities for the Fairness Pipeline Development Toolkit.

This module provides loaders for the German Credit dataset (UCI/OpenML),
the primary fairness benchmark used throughout the toolkit. The dataset
is a classic credit scoring scenario with known demographic disparities,
making it ideal for demonstrating and testing fairness interventions.

The loader handles:
    - Fetching from OpenML (data_id=31, 1000 instances)
    - Extracting protected attributes (sex, age_group)
    - One-hot encoding categorical features
    - Stratified train/test splitting to preserve class balance
"""

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.datasets import fetch_openml


def load_german_credit(
    test_size: float = 0.3,
    random_state: int = 42,
    as_frame: bool = True,
) -> dict:
    """Load and preprocess the German Credit dataset from OpenML.

    The German Credit dataset contains 1,000 credit applications with 20
    features. The target variable indicates whether the applicant was
    classified as a good (1) or bad (0) credit risk. Two protected
    attributes are extracted for fairness analysis.

    Parameters
    ----------
    test_size : float, default 0.3
        Proportion of the dataset to hold out for testing.
    random_state : int, default 42
        Random seed for reproducible train/test splits.
    as_frame : bool, default True
        Whether to return data as DataFrame (passed to OpenML fetcher).

    Returns
    -------
    dict
        Dictionary with the following keys:
        - X_train, X_test:         Feature matrices (ndarray)
        - y_train, y_test:         Target labels (ndarray, binary 0/1)
        - sensitive_train/test:    DataFrame with protected attributes
        - feature_names:           List of encoded feature column names
        - sensitive_columns:       ['sex', 'age_group']
        - target_name:             'credit_risk'
        - positive_label:          'good credit'

    Protected Attributes
    --------------------
    - sex: Derived from the 'personal_status' field. Values: 'male', 'female'.
    - age_group: Binarized from numeric age. Values: 'young' (< 25), 'old' (>= 25).
      The 25-year threshold follows standard practice in credit fairness literature.
    """
    # Fetch the raw dataset from OpenML (UCI German Credit, data_id=31)
    data = fetch_openml(data_id=31, as_frame=True, parser="auto")
    df = data.data.copy()

    # Encode the target: "good" credit → 1 (positive), "bad" → 0
    df["target"] = (data.target == "good").astype(int)

    # --- Extract protected attributes ---
    # The original dataset encodes sex within the 'personal_status' field
    # (e.g., "male single", "female div/dep/mar"). We parse it out.
    df["sex"] = df["personal_status"].apply(_extract_sex)

    # Age is binarized at 25: applicants under 25 are considered "young"
    # and may face age-based discrimination in lending decisions.
    if "age" in df.columns:
        df["age_group"] = df["age"].apply(lambda a: "young" if a < 25 else "old")
    else:
        df["age_group"] = "old"

    sensitive_columns = ["sex", "age_group"]

    # --- Prepare the feature matrix ---
    # Drop the target, protected attributes, and the raw personal_status
    # field (which would leak sex information into the model).
    drop_cols = ["personal_status", "target"] + sensitive_columns
    feature_cols = [c for c in df.columns if c not in drop_cols]

    # One-hot encode categorical features (drop_first=True avoids
    # multicollinearity). All values cast to float for sklearn compatibility.
    df_encoded = pd.get_dummies(df[feature_cols], drop_first=True).astype(float)
    feature_names = list(df_encoded.columns)

    X = df_encoded.values
    y = df["target"].values
    sensitive = df[sensitive_columns].copy().reset_index(drop=True)

    # Stratified split ensures the class distribution (good/bad credit)
    # is preserved in both train and test sets.
    X_train, X_test, y_train, y_test, sens_train, sens_test = train_test_split(
        X, y, sensitive, test_size=test_size, random_state=random_state, stratify=y
    )

    return {
        "X_train": X_train,
        "X_test": X_test,
        "y_train": y_train,
        "y_test": y_test,
        "sensitive_train": sens_train.reset_index(drop=True),
        "sensitive_test": sens_test.reset_index(drop=True),
        "feature_names": feature_names,
        "sensitive_columns": sensitive_columns,
        "target_name": "credit_risk",
        "positive_label": "good credit",
    }


def _extract_sex(personal_status: str) -> str:
    """Extract sex from the German Credit 'personal_status' field.

    The original dataset combines sex and marital status into a single
    categorical feature (e.g., 'male : single', 'female : div/dep/mar').
    This helper parses the sex component.

    Parameters
    ----------
    personal_status : str
        Raw value from the 'personal_status' column.

    Returns
    -------
    str
        'female' if the status contains 'female', otherwise 'male'.
    """
    ps = str(personal_status).lower()
    if "female" in ps:
        return "female"
    return "male"
