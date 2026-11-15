from typing import Any


METRICS = ("accuracy", "precision", "recall", "f1", "roc_auc")
DEFAULT_TOLERANCES = {name: 0.02 for name in METRICS}


def calculate_score(
    *,
    integrity_verified: bool,
    configuration_matches: bool,
    original_metrics: dict[str, float],
    reproduced_metrics: dict[str, float],
    environment_original: dict[str, str],
    environment_reproduced: dict[str, str],
    tolerances: dict[str, float],
) -> dict[str, Any]:
    reasons: list[str] = []
    artifact_points = 40.0 if integrity_verified else 0.0
    if not integrity_verified:
        reasons.append("Critical evidence integrity or blockchain anchoring is missing or failed.")

    configuration_points = 20.0 if configuration_matches else 0.0
    if not configuration_matches:
        reasons.append("Reproduction configuration differs from the registered configuration.")

    present_metrics = [key for key in METRICS if key in original_metrics and key in reproduced_metrics]
    if present_metrics:
        agreed = sum(
            abs(float(original_metrics[key]) - float(reproduced_metrics[key]))
            <= tolerances.get(key, DEFAULT_TOLERANCES[key])
            for key in present_metrics
        )
        metric_points = 30.0 * agreed / len(METRICS)
        if len(present_metrics) != len(METRICS):
            reasons.append("One or more required metrics are missing.")
        if agreed != len(present_metrics):
            reasons.append("One or more reproduced metrics exceeded configured tolerances.")
    else:
        metric_points = 0.0
        reasons.append("No comparable evaluation metrics are available.")

    common_environment = set(environment_original) & set(environment_reproduced)
    environment_points = (
        10.0
        * sum(environment_original[key] == environment_reproduced[key] for key in common_environment)
        / len(environment_original)
        if environment_original
        else 0.0
    )
    if environment_points < 10:
        reasons.append("Runtime environment differs or environment evidence is incomplete.")

    total = artifact_points + configuration_points + metric_points + environment_points
    if not integrity_verified:
        total = min(total, 30.0)
    return {
        "total": round(total, 2),
        "components": {
            "artifact_integrity": round(artifact_points, 2),
            "configuration_match": round(configuration_points, 2),
            "metric_agreement": round(metric_points, 2),
            "environment_match": round(environment_points, 2),
        },
        "reasons": reasons or ["All configured checks matched; this score is a proposed project metric, not a universal scientific measure."],
    }

