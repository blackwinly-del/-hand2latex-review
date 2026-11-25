from reasoning.context import choose_with_context
from reasoning.validators import find_ambiguous_glyph_conflicts, validate_structure


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
    has_conflict = len(deduplicated) > 1
    context_result = None
    if has_conflict:
        context_result = choose_with_context(image_path, deduplicated)
        if context_result["selected_index"] is not None:
            selected = deduplicated[context_result["selected_index"]]

    raw_latex = selected["latex"]
    final_latex = normalize_latex(raw_latex)
    changes = []
    if selected is not deduplicated[0]:
        changes.append(
            {
                "rule": "context_candidate_selection",
                "before": deduplicated[0]["latex"],
                "after": raw_latex,
                "selected_index": context_result["selected_index"],
                "reason": context_result["reason"],
            }
        )
    if final_latex != raw_latex:
        changes.append(
            {
                "rule": "trim_outer_whitespace",
                "before": raw_latex,
                "after": final_latex,
            }
        )

    has_structure_issues = any(
        validate_structure(normalize_latex(candidate["latex"]))
        for candidate in deduplicated
    )
    ambiguity_issues = find_ambiguous_glyph_conflicts(deduplicated)
    context_failed = has_conflict and context_result["selected_index"] is None
    need_review = context_failed or has_structure_issues or bool(ambiguity_issues)
    matching_engines = {
        candidate.get("engine")
        for candidate in candidates
        if candidate.get("error") is None
        and normalize_latex(candidate["latex"]) == final_latex
        and candidate.get("engine")
    }
    if need_review:
        confidence = "low"
    elif not has_conflict and len(matching_engines) > 1:
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
