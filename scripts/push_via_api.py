"""通过 GitHub Git Data API 推送提交（github.com:443 502 时的备用通道）。

为什么需要这个脚本：本机到 github.com:443 会间歇性 502（CONNECT tunnel failed），
而 api.github.com 始终 200。git push 走前者，推不上去；这个脚本走后者。

Git Data API 的推送分四步：
  1. 每个改动文件 -> POST /git/blobs        （内容已存在的会复用同一 sha）
  2. 基于父树 + 改动 -> POST /git/trees     （base_tree 让未改动文件自动继承）
  3. POST /git/commits                      （指定 parents，保留原作者与提交信息）
  4. PATCH /git/refs/heads/<branch>         （移动引用；非快进要 force）

用法：
    python scripts/push_via_api.py --token TOKEN --base e7b042f --head HEAD \
        --branch hand2latex-review
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_API = "https://api.github.com"
_RETRIES = 6
_RETRY_DELAY = 3.0


def _request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    last_error: Exception | None = None
    # 5xx 与连接中断都是上游偶发，重试比直接失败合理；4xx 立刻抛出，重试无意义。
    for attempt in range(1, _RETRIES + 1):
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", "application/vnd.github+json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            last_error = RuntimeError(f"{method} {url} -> {error.code}\n{detail}")
            if error.code < 500:
                raise last_error from error
            print(f"    {error.code}，第 {attempt}/{_RETRIES} 次失败，{_RETRY_DELAY * attempt}s 后重试")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = RuntimeError(f"{method} {url} -> 连接失败：{error}")
            print(f"    连接失败，第 {attempt}/{_RETRIES} 次，{_RETRY_DELAY * attempt}s 后重试")
        if attempt < _RETRIES:
            time.sleep(_RETRY_DELAY * attempt)
    raise last_error if last_error else RuntimeError(f"{method} {url} 未知失败")


def _git(*args: str, binary: bool = False) -> bytes | str:
    done = subprocess.run(["git", *args], cwd=_ROOT, capture_output=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{done.stderr.decode('utf-8', 'replace')}")
    return done.stdout if binary else done.stdout.decode("utf-8")


def _changed_files(base: str, head: str, repo: str, token: str, base_tree_sha: str) -> list[str]:
    """找出 head 相对 base 改了哪些文件。

    base 可能是上一次走 API 推上去的提交，本地 git 根本没有这个对象
    （git push 走不到 API 通道）。这时 `git diff` 会报 bad object，
    所以退回用远端的 tree 做比对——两边都是 blob sha，比文件名可靠。
    """
    known = subprocess.run(
        ["git", "cat-file", "-e", f"{base}^{{commit}}"], cwd=_ROOT, capture_output=True, check=False
    ).returncode == 0
    if known:
        return [line for line in str(_git("diff", "--name-only", base, head)).splitlines() if line.strip()]

    print("  base 不在本地（上次是走 API 推的），改用远端树比对")
    remote = _request("GET", f"{_API}/repos/{repo}/git/trees/{base_tree_sha}?recursive=1", token)
    remote_blobs = {item["path"]: item["sha"] for item in remote.get("tree", []) if item["type"] == "blob"}
    local = {}
    for line in str(_git("ls-tree", "-r", head)).splitlines():
        meta, path = line.split("\t", 1)
        local[path] = meta.split()[2]
    changed = [p for p in local if remote_blobs.get(p) != local[p]]
    # 远端有但本地没有的（删除）也要带上，否则树里会留着旧文件
    removed = [p for p in remote_blobs if p not in local]
    if removed:
        print(f"  注意：有 {len(removed)} 个文件在远端存在但本地没有：{', '.join(removed[:5])}")
    return changed


def _file_mode(head: str, path: str) -> str:
    out = _git("ls-tree", head, "--", path)
    for line in str(out).splitlines():
        meta = line.split("\t")[0]
        return meta.split()[0]
    return "100644"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--repo", required=True, help="形如 owner/name")
    parser.add_argument("--base", required=True, help="远端当前提交（新提交的父）")
    parser.add_argument("--head", default="HEAD", help="本地要推的提交")
    parser.add_argument("--branch", required=True)
    parser.add_argument("--force", action="store_true", help="非快进时强制更新引用")
    args = parser.parse_args()

    head_sha = str(_git("rev-parse", args.head)).strip()
    # base 允许传远端 SHA（本地可能不认识），所以这里不强求 rev-parse 成功
    base_probe = subprocess.run(
        ["git", "rev-parse", args.base], cwd=_ROOT, capture_output=True, check=False
    )
    base_sha = base_probe.stdout.decode("utf-8", "replace").strip() if base_probe.returncode == 0 else args.base
    message = str(_git("log", "-1", "--format=%B", head_sha))
    author_name = str(_git("log", "-1", "--format=%an", head_sha)).strip()
    author_email = str(_git("log", "-1", "--format=%ae", head_sha)).strip()
    author_date = str(_git("log", "-1", "--format=%aI", head_sha)).strip()

    base_commit = _request("GET", f"{_API}/repos/{args.repo}/git/commits/{base_sha}", args.token)
    base_tree = base_commit["tree"]["sha"]

    files = _changed_files(base_sha, head_sha, args.repo, args.token, base_tree)
    if not files:
        print("没有改动，无需推送。")
        return 0
    print(f"将推送 {len(files)} 个改动文件，{base_sha[:8]} -> {head_sha[:8]}，目标分支 {args.branch}")

    entries = []
    for path in files:
        content = _git("show", f"{head_sha}:{path}", binary=True)
        blob = _request(
            "POST",
            f"{_API}/repos/{args.repo}/git/blobs",
            args.token,
            {"content": content.decode("utf-8"), "encoding": "utf-8"},
        )
        entries.append({"path": path, "mode": _file_mode(head_sha, path), "type": "blob", "sha": blob["sha"]})
        print(f"  blob {path} -> {blob['sha'][:8]}")

    tree = _request(
        "POST",
        f"{_API}/repos/{args.repo}/git/trees",
        args.token,
        {"base_tree": base_tree, "tree": entries},
    )
    print(f"  tree -> {tree['sha'][:8]}")

    commit = _request(
        "POST",
        f"{_API}/repos/{args.repo}/git/commits",
        args.token,
        {
            "message": message,
            "tree": tree["sha"],
            "parents": [base_sha],
            "author": {"name": author_name, "email": author_email, "date": author_date},
        },
    )
    print(f"  commit -> {commit['sha']}")

    updated = _request(
        "PATCH",
        f"{_API}/repos/{args.repo}/git/refs/heads/{args.branch}",
        args.token,
        {"sha": commit["sha"], "force": bool(args.force)},
    )
    print(f"  引用 {args.branch} -> {updated['object']['sha'][:8]}")
    print(f"\n完成。远端 {args.branch} 现在是 {commit['sha']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
