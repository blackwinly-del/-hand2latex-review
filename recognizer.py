import time
from pathlib import Path

_MODEL = None
_MODEL_DIR = Path(__file__).resolve().parent / "models" / "PP-FormulaNet-L"


def recognize(image_path: str) -> list[dict]:
    global _MODEL
    if _MODEL is None:
        from paddleocr import FormulaRecognition

        _MODEL = FormulaRecognition(
            model_name="PP-FormulaNet-L",
            model_dir=str(_MODEL_DIR),
            device="cpu",
        )

    started = time.perf_counter()
    try:
        outputs = _MODEL.predict(input=image_path, batch_size=1)
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        formulas = [result["rec_formula"] for result in outputs]
        if not formulas:
            return [
                {
                    "engine": "pp_formulanet_l",
                    "latex": "",
                    "score": None,
                    "latency_ms": latency_ms,
                    "error": "model returned no formula",
                }
            ]
        return [
            {
                "engine": "pp_formulanet_l",
                "latex": formula,
                "score": None,
                "latency_ms": latency_ms,
                "error": None,
            }
            for formula in formulas
        ]
    except Exception as error:
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        return [
            {
                "engine": "pp_formulanet_l",
                "latex": "",
                "score": None,
                "latency_ms": latency_ms,
                "error": f"{type(error).__name__}: {error}",
            }
        ]
