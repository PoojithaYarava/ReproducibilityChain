import importlib.util
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.datasets import load_breast_cancer
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression


ALLOWED_MODELS = {
    "logistic_regression": {
        "estimator": LogisticRegression,
        "parameters": {"C", "max_iter"},
        "defaults": {"C": 1.0, "max_iter": 1000},
    },
    "random_forest": {
        "estimator": RandomForestClassifier,
        "parameters": {"n_estimators", "max_depth"},
        "defaults": {"n_estimators": 100, "max_depth": None},
    },
    "decision_tree": {
        "estimator": DecisionTreeClassifier,
        "parameters": {"max_depth", "min_samples_split"},
        "defaults": {"max_depth": None, "min_samples_split": 2},
    },
}


def environment_info() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "scikit_learn": sklearn.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "platform": platform.platform(),
    }


def _make_model(model_name: str, parameters: dict[str, Any], seed: int):
    if model_name not in ALLOWED_MODELS:
        raise ValueError("Unsupported model architecture")
    spec = ALLOWED_MODELS[model_name]
    unknown = set(parameters) - spec["parameters"]
    if unknown:
        raise ValueError(f"Unsupported hyperparameters: {', '.join(sorted(unknown))}")
    values = {**spec["defaults"], **parameters}
    if model_name == "logistic_regression":
        if (
            isinstance(values["C"], bool)
            or not isinstance(values["C"], (int, float))
            or float(values["C"]) <= 0
            or isinstance(values["max_iter"], bool)
            or not isinstance(values["max_iter"], int)
            or values["max_iter"] < 1
        ):
            raise ValueError("C must be positive and max_iter must be at least 1")
        values["C"] = float(values["C"])
    elif model_name == "random_forest":
        if (
            isinstance(values["n_estimators"], bool)
            or not isinstance(values["n_estimators"], int)
            or values["n_estimators"] < 1
            or (
                values["max_depth"] is not None
                and (
                    isinstance(values["max_depth"], bool)
                    or not isinstance(values["max_depth"], int)
                    or values["max_depth"] < 1
                )
            )
        ):
            raise ValueError("Invalid random forest hyperparameters")
    elif model_name == "decision_tree":
        if (
            isinstance(values["min_samples_split"], bool)
            or not isinstance(values["min_samples_split"], int)
            or values["min_samples_split"] < 2
            or (
                values["max_depth"] is not None
                and (
                    isinstance(values["max_depth"], bool)
                    or not isinstance(values["max_depth"], int)
                    or values["max_depth"] < 1
                )
            )
        ):
            raise ValueError("Invalid decision tree hyperparameters")
    return spec["estimator"](**values, random_state=seed), values


def run_pipeline(
    *,
    model_name: str,
    parameters: dict[str, Any],
    seed: int,
    artifact_directory: Path,
    source_repository: str | None = None,
    git_commit: str | None = None,
) -> dict[str, Any]:
    artifact_directory.mkdir(parents=True, exist_ok=True)
    dataset = load_breast_cancer(as_frame=True)
    features = dataset.data
    target = dataset.target
    x_train, x_test, y_train, y_test = train_test_split(
        features,
        target,
        test_size=0.2,
        random_state=seed,
        stratify=target,
    )
    estimator, normalized_parameters = _make_model(model_name, parameters, seed)

    dataset_file = artifact_directory / "dataset.csv"
    data = features.copy()
    data["target"] = target
    data.to_csv(dataset_file, index=False, lineterminator="\n")

    started = time.perf_counter()
    estimator.fit(x_train, y_train)
    predictions = estimator.predict(x_test)
    probabilities = estimator.predict_proba(x_test)[:, 1]
    execution_seconds = time.perf_counter() - started

    metrics = {
        "accuracy": float(accuracy_score(y_test, predictions)),
        "precision": float(precision_score(y_test, predictions, zero_division=0)),
        "recall": float(recall_score(y_test, predictions, zero_division=0)),
        "f1": float(f1_score(y_test, predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
    }
    matrix = confusion_matrix(y_test, predictions).astype(int).tolist()
    configuration = {
        "model_name": model_name,
        "hyperparameters": normalized_parameters,
        "random_seed": seed,
        "dataset_name": "breast_cancer",
        "dataset_version": "sklearn-bundled",
        "test_size": 0.2,
        "stratified": True,
    }
    environment = environment_info()

    model_path = artifact_directory / "model.joblib"
    joblib.dump(estimator, model_path)
    (artifact_directory / "configuration.json").write_text(
        json.dumps(configuration, sort_keys=True, indent=2), encoding="utf-8"
    )
    (artifact_directory / "environment.json").write_text(
        json.dumps(environment, sort_keys=True, indent=2), encoding="utf-8"
    )
    (artifact_directory / "metrics.json").write_text(
        json.dumps(
            {
                "metrics": metrics,
                "confusion_matrix": matrix,
                "execution_seconds": execution_seconds,
            },
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    (artifact_directory / "source_reference.json").write_text(
        json.dumps(
            {
                "repository": source_repository or "",
                "git_commit": git_commit or "",
                "pipeline": "ReproducibilityChain controlled sklearn pipeline v1",
            },
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    (artifact_directory / "source_code_snapshot.py").write_bytes(
        Path(__file__).resolve().read_bytes()
    )

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    if tracking_uri:
        if importlib.util.find_spec("mlflow") is None:
            raise RuntimeError(
                "MLFLOW_TRACKING_URI is set but MLflow is not installed; "
                "install the optional mlflow dependency or unset the variable"
            )
        import mlflow

        mlflow.set_tracking_uri(tracking_uri)
        with mlflow.start_run():
            mlflow.log_params(
                {
                    "model_name": model_name,
                    "random_seed": seed,
                    **{
                        f"hyperparameter_{key}": str(value)
                        for key, value in normalized_parameters.items()
                    },
                }
            )
            mlflow.log_metrics(metrics)
            mlflow.log_artifacts(str(artifact_directory))

    return {
        "metrics": metrics,
        "confusion_matrix": matrix,
        "execution_seconds": execution_seconds,
        "configuration": configuration,
        "environment": environment,
    }
