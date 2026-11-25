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
import base64
import json
import os
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


def _remote_blobs(repo: str, token: str, tree_sha: str) -> dict[str, str] | None:
    """取远端某个树里 {路径: blob sha}。取不到时返回 None，由调用方决定要不要继续。"""
    try:
        remote = _request("GET", f"{_API}/repos/{repo}/git/trees/{tree_sha}?recursive=1", token)
    except RuntimeError:
        return None
    if remote.get("truncated"):
        # 文件太多时 GitHub 会截断，这时比对结果不可信，宁可退回逐文件计算。
        return None
    return {item["path"]: item["sha"] for item in remote.get("tree", []) if item["type"] == "blob"}


def _changed_files(base: str, head: str, repo: str, token: str, base_tree_sha: str) -> list[tuple[str, bool]]:
    """找出 head 相对 base 改了哪些文件，返回 [(路径, 是否删除)]。

    base 可能是上一次走 API 推上去的提交，本地 git 根本没有这个对象
    （git push 走不到 API 通道）。这时 `git diff` 会报 bad object，
    所以退回用远端的 tree 做比对——两边都是 blob sha，比文件名可靠。

    必须带上"是否删除"：删除的文件在 head 里取不到内容（`git show` 退出码 128），
    当成普通改动去取 blob 会整批崩掉。树里要删掉一个条目，得显式写
    {"sha": None}，光"不发这个条目"是删不掉的（base_tree 会把它继承回来）。
    """
    known = subprocess.run(
        ["git", "cat-file", "-e", f"{base}^{{commit}}"], cwd=_ROOT, capture_output=True, check=False
    ).returncode == 0
    if known:
        changes: list[tuple[str, bool]] = []
        for line in str(_git("diff", "--name-status", base, head)).splitlines():
            if not line.strip():
                continue
            fields = line.split("\t")
            status, path = fields[0], fields[-1]
            # R100 之类的重命名状态也算"旧路径删除 + 新路径新增"，--name-status 会给两个路径。
            changes.append((path, status.startswith("D")))
        return changes

    print("  base 不在本地（上次是走 API 推的），改用远端树比对")
    remote_blobs = _remote_blobs(repo, token, base_tree_sha) or {}
    local = {}
    for line in str(_git("ls-tree", "-r", head)).splitlines():
        meta, path = line.split("\t", 1)
        local[path] = meta.split()[2]
    changes = [(p, False) for p in local if remote_blobs.get(p) != local[p]]
    # 远端有但本地没有的，是删除：必须显式进 entries，否则树里会留着旧文件。
    removed = [p for p in remote_blobs if p not in local]
    if removed:
        print(f"  远端有 {len(removed)} 个文件本地已删除：{', '.join(removed[:5])}")
        changes.extend((p, True) for p in removed)
    return changes


def _file_mode(head: str, path: str) -> str:
    out = _git("ls-tree", head, "--", path)
    for line in str(out).splitlines():
        meta = line.split("\t")[0]
        return meta.split()[0]
    return "100644"


def main() -> int:
    parser = argparse.ArgumentParser()
    # token 不要走命令行：argv 会进 shell 历史、进进程列表（ps/tasklist 都能看到），
    # 一台机器上任何用户都能读到。默认从环境变量取，--token 只为兼容旧用法保留。
    parser.add_argument("--token", default=None, help="GitHub token；不传则读 GITHUB_TOKEN 环境变量")
    parser.add_argument("--repo", required=True, help="形如 owner/name")
    parser.add_argument("--base", required=True, help="远端当前提交（新提交的父）")
    parser.add_argument("--head", default="HEAD", help="本地要推的提交")
    parser.add_argument("--branch", required=True)
    parser.add_argument("--force", action="store_true", help="非快进时强制更新引用")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要做什么，不写远端")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("缺少 token：请设置环境变量 GITHUB_TOKEN，或用 --token 传入（不推荐，会留在命令历史里）。", file=sys.stderr)
        return 2

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

    base_commit = _request("GET", f"{_API}/repos/{args.repo}/git/commits/{base_sha}", token)
    base_tree = base_commit["tree"]["sha"]

    # 幂等闸门：远端树的 blob 与本地完全一致时，内容其实已经推上去了，
    # 再走一遍 commits 只会造出一个树相同、父提交不同的新提交——
    # 同一条改动在远端出现两次，历史被无意义地拉长（8038b9d 与 8e9dd00 就是这么来的）。
    local_blobs = {}
    for line in str(_git("ls-tree", "-r", head_sha)).splitlines():
        meta, path = line.split("\t", 1)
        local_blobs[path] = meta.split()[2]
    remote_blobs = _remote_blobs(args.repo, token, base_tree)
    if remote_blobs is not None and remote_blobs == local_blobs:
        print(f"远端 {args.branch} 的树与本地 {head_sha[:8]} 完全一致（{len(local_blobs)} 个文件），无需推送。")
        return 0

    files = _changed_files(base_sha, head_sha, args.repo, token, base_tree)
    if not files:
        print("没有改动，无需推送。")
        return 0
    added = sum(1 for _, deleted in files if not deleted)
    deleted_count = len(files) - added
    print(
        f"将推送 {len(files)} 个改动（新增/修改 {added}，删除 {deleted_count}），"
        f"{base_sha[:8]} -> {head_sha[:8]}，目标分支 {args.branch}"
    )
    if args.dry_run:
        for path, deleted in files:
            print(f"  [dry-run] {'删除' if deleted else '写入'} {path}")
        return 0

    entries = []
    for path, deleted in files:
        if deleted:
            # 树里删条目要显式写 sha=None；不发这个条目的话 base_tree 会把它继承回来。
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            print(f"  delete {path}")
            continue
        content = _git("show", f"{head_sha}:{path}", binary=True)
        # 必须走 base64。仓库里有 385 个二进制文件（data/page_math/*.png 353 张、
        # artifacts/ 7、docs/ 7、samples/ 1），按 utf-8 编码它们会抛
        # UnicodeDecodeError（pm_001.png 第 0 字节就是 0x89）。只推文本文件的场景
        # 从来碰不到这个问题，一旦推到图就整批失败。
        blob = _request(
            "POST",
            f"{_API}/repos/{args.repo}/git/blobs",
            token,
            {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
        )
        entries.append({"path": path, "mode": _file_mode(head_sha, path), "type": "blob", "sha": blob["sha"]})
        print(f"  blob {path} -> {blob['sha'][:8]}")

    tree = _request(
        "POST",
        f"{_API}/repos/{args.repo}/git/trees",
        token,
        {"base_tree": base_tree, "tree": entries},
    )
    print(f"  tree -> {tree['sha'][:8]}")

    commit = _request(
        "POST",
        f"{_API}/repos/{args.repo}/git/commits",
        token,
        {
            "message": message,
            "tree": tree["sha"],
            "parents": [base_sha],
            "author": {"name": author_name, "email": author_email, "date": author_date},
        },
    )
    print(f"  commit -> {commit['sha']}")

    # --force 会静默覆盖远端已有提交，丢掉别人的提交也只会在事后才发现，所以要先问一次。
    if args.force:
        print(f"\n--force：将强制把 {args.branch} 从 {base_sha[:8]} 移到 {commit['sha'][:8]}。")
        print("如果远端有别人推的提交，那些提交会从分支上消失（仍可在 reflog 里找回）。")
        try:
            answer = input("确认继续？输入 yes 继续：").strip().lower()
        except EOFError:
            answer = ""
        if answer != "yes":
            print("已取消。远端未改动。")
            return 1

    updated = _request(
        "PATCH",
        f"{_API}/repos/{args.repo}/git/refs/heads/{args.branch}",
        token,
        {"sha": commit["sha"], "force": bool(args.force)},
    )
    print(f"  引用 {args.branch} -> {updated['object']['sha'][:8]}")
    print(f"\n完成。远端 {args.branch} 现在是 {commit['sha']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
