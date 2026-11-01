from reasoning.validators import validate_structure

FEATURE_NAMES = (
    "candidate_count",
    "valid_candidate_count",
    "engine_count",
    "error_candidate_count",
    "structure_issue_count",
    "has_conflict",
    "selected_latex_length",
    "selected_script_count",
)


def extract_features(candidates: list[dict]) -> list[float]:
    if not isinstance(candidates, list):
        raise TypeError("candidates must be a list")

    valid_candidates = []
    supporting_engines = set()
    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise TypeError("each candidate must be a dict")
        if "latex" not in candidate:
            raise ValueError("candidate is missing latex")
        latex = candidate["latex"]
        if not isinstance(latex, str):
            raise TypeError("latex must be a string")
        normalized = latex.strip()
        if candidate.get("error") is not None or not normalized:
            continue
        if candidate.get("engine"):
            supporting_engines.add(candidate["engine"])
        if normalized in seen:
            continue
        seen.add(normalized)
        valid_candidates.append((candidate, normalized))

    selected = valid_candidates[0][1] if valid_candidates else ""
    values = (
        len(candidates),
        len(valid_candidates),
        len(supporting_engines),
        sum(candidate.get("error") is not None for candidate in candidates),
        sum(len(validate_structure(latex)) for _, latex in valid_candidates),
        len(valid_candidates) > 1,
        len(selected),
        selected.count("^") + selected.count("_"),
    )
    return [float(value) for value in values]
