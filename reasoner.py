from reasoning.validators import validate_structure


def normalize_latex(latex: str) -> str:
    if not isinstance(latex, str):
        raise TypeError("latex must be a string")
    return latex.strip()


def deduplicate_candidates(candidates: list[dict]) -> list[dict]:
    if not isinstance(candidates, list):
        raise TypeError("candidates must be a list")

    deduplicated = []
    seen = set()

    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise TypeError("each candidate must be a dict")
        if "latex" not in candidate:
            raise ValueError("candidate is missing latex")

        normalized = normalize_latex(candidate["latex"])
        if candidate.get("error") is not None or not normalized or normalized in seen:
            continue

        seen.add(normalized)
        deduplicated.append(candidate)

    return deduplicated


def refine(image_path: str, candidates: list[dict]) -> dict:
    deduplicated = deduplicate_candidates(candidates)
    if not deduplicated:
        return {
            "raw_latex": "",
            "final_latex": "",
            "confidence": "low",
            "changes": [],
            "need_review": True,
            "risk_score": None,
        }

    selected = deduplicated[0]
    raw_latex = selected["latex"]
    final_latex = normalize_latex(raw_latex)
    changes = []
    if final_latex != raw_latex:
        changes.append(
            {
                "rule": "trim_outer_whitespace",
                "before": raw_latex,
                "after": final_latex,
            }
        )

    structure_issues = validate_structure(final_latex)
    has_conflict = len(deduplicated) > 1
    need_review = has_conflict or bool(structure_issues)
    matching_engines = {
        candidate.get("engine")
        for candidate in candidates
        if candidate.get("error") is None
        and normalize_latex(candidate["latex"]) == final_latex
        and candidate.get("engine")
    }
    if need_review:
        confidence = "low"
    elif len(matching_engines) > 1:
        confidence = "high"
    else:
        confidence = "medium"

    return {
        "raw_latex": raw_latex,
        "final_latex": final_latex,
        "confidence": confidence,
        "changes": changes,
        "need_review": need_review,
        "risk_score": None,
    }
