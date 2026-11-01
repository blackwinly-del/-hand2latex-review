import json
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_NODE_SCRIPT = r"""
const katex = require("katex");
let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => input += chunk);
process.stdin.on("end", () => {
  try {
    const payload = JSON.parse(input);
    katex.renderToString(payload.latex, {
      displayMode: true,
      throwOnError: true,
      strict: false
    });
    process.stdout.write(JSON.stringify({error: null}));
  } catch (error) {
    if (error instanceof katex.ParseError) {
      process.stdout.write(JSON.stringify({error: error.message}));
      process.exitCode = 2;
    } else {
      process.stderr.write(error.message);
      process.exitCode = 1;
    }
  }
});
"""


def check_renderable(latex: str) -> dict:
    if not isinstance(latex, str):
        raise TypeError("latex must be a string")

    try:
        completed = subprocess.run(
            ["node", "-e", _NODE_SCRIPT],
            input=json.dumps({"latex": latex}),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=_PROJECT_ROOT,
        )
    except FileNotFoundError as error:
        raise RuntimeError("Node.js is required for render checking") from error
    except OSError as error:
        raise RuntimeError(f"render checker could not start: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("render checking timed out") from error

    if completed.returncode not in (0, 2):
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"render checker failed: {detail}")

    try:
        result = json.loads(completed.stdout)
        error = result["error"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise RuntimeError("render checker returned invalid output") from error
    if completed.returncode == 0 and error is None:
        return {"renderable": True, "error": None}
    if completed.returncode == 2 and isinstance(error, str) and error:
        return {"renderable": False, "error": error}
    raise RuntimeError("render checker returned invalid output")
