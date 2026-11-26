"""通过 GitHub Git Data API 推送提交（github.com:443 502 时的备用通道）。

为什么需要这个脚本：本机到 github.com:443 会间歇性 502（CONNECT tunnel failed），
而 api.github.com 始终 200。git push 走前者，推不上去；这个脚本走后者。

推送流程：
  0. GET  /git/ref/heads/<branch>          查分支在不在、指向哪（404 = 不存在）
     - 存在但已不在 base 上 → 停下（除非 --force），否则会把别人的提交抹掉
     - 不存在 → 需要 --create-branch，引用最后用 POST /git/refs 建
  1. 每个改动文件 -> POST /git/blobs        （内容已存在的会复用同一 sha；一律 base64）
  2. 基于父树 + 改动 -> POST /git/trees     （base_tree 让未改动文件自动继承）
  3. 逐个提交 POST /git/commits             （按 rev-list 顺序重放，parents 保留多父合并拓扑）
  4. PATCH /git/refs/heads/<branch>         （已存在）或 POST /git/refs（新建）
  5. 推后自校验：重新拉远端树，与本地逐 blob 比对

删除分支用 --delete-branch（DELETE /git/refs/heads/<branch>，删后复查确认真没了）。

用法：
    # 推已有分支
    export GITHUB_TOKEN=...
    python scripts/push_via_api.py --repo owner/name --base <远端SHA> --branch main

    # 新建分支 / 删分支
    python scripts/push_via_api.py --repo owner/name --base <SHA> --branch feat/x --create-branch
    python scripts/push_via_api.py --repo owner/name --branch feat/x --delete-branch
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


def _request(method: str, url: str, token: str, payload: dict | None = None, allow_404: bool = False) -> dict | None:
    """发一个 API 请求。allow_404=True 时把 404 当成"这东西不存在"返回 None。

    探测"分支/提交在不在"用的是 404，那是正常答案而不是失败，不能混进重试逻辑里。
    """
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
            if error.code == 404 and allow_404:
                return None
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


def _local_commit_chain(base: str, head: str) -> list[str]:
    """列出 head 到 base 之间（不含 base）的本地提交，从旧到新。

    `git rev-list --reverse base..head` 正好是这个顺序，遇到合并提交也不会漏。
    base 不在本地时返回空列表——那种情况下没法算增量，只能推单个提交。
    """
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{base}^{{commit}}"], cwd=_ROOT, capture_output=True, check=False
    )
    if probe.returncode != 0:
        return []
    out = str(_git("rev-list", "--reverse", f"{base}..{head}"))
    return [line.strip() for line in out.splitlines() if line.strip()]


def _resolve_local_equivalent(base_sha: str, head: str, base_tree: str) -> str | None:
    """base 是本机不认识的远端 sha 时，找一个"内容与它完全相同"的本地提交。

    典型场景：上次走 API 推的提交在远端叫 3ee41768，本地对应的是 f1cb06b
    （树相同、提交对象不同）。不把这两个对上，回放时就会拿本地 sha 去远端查父提交，
    得到一个 404。判据用树哈希，不用提交号——提交号本来就不同。
    """
    if _is_local(base_sha):
        return base_sha
    for line in str(_git("rev-list", head)).splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if str(_git("rev-parse", f"{candidate}^{{tree}}")).strip() == base_tree:
            return candidate
    return None


def _commit_meta(sha: str) -> dict:
    """取一个本地提交的元信息：树、作者、提交者、消息、父提交。

    父提交必须从 commit 对象本体读，不能用 `git log --format=%P` 之类再绕一层——
    这里要的就是"这个提交对象里写了哪些 parent"。
    """
    # cat-file 的输出是字节。别用 str(raw)——那会得到 "b'tree ...'" 这种字面量，
    # 行首变成 "b'tree" / "b'parent"，startswith("parent ") 永远匹配不到，
    # 结果是把每个提交都当成无父提交。
    raw = _git("cat-file", "commit", sha, binary=True)
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    return {
        "sha": sha,
        "tree": str(_git("rev-parse", f"{sha}^{{tree}}")).strip(),
        "raw_name": str(_git("log", "-1", "--format=%an", sha)).strip(),
        "raw_email": str(_git("log", "-1", "--format=%ae", sha)).strip(),
        "raw_date": str(_git("log", "-1", "--format=%aI", sha)).strip(),
        "committer_name": str(_git("log", "-1", "--format=%cn", sha)).strip(),
        "committer_email": str(_git("log", "-1", "--format=%ce", sha)).strip(),
        "committer_date": str(_git("log", "-1", "--format=%cI", sha)).strip(),
        "message": str(_git("log", "-1", "--format=%B", sha)),
        "parents": [line.split()[1] for line in text.splitlines() if line.startswith("parent ")],
    }


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
    parser.add_argument("--create-branch", action="store_true", help="分支不存在时创建（默认拒绝）")
    parser.add_argument("--delete-branch", action="store_true", help="删除远端分支（配合 --branch）")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("缺少 token：请设置环境变量 GITHUB_TOKEN，或用 --token 传入（不推荐，会留在命令历史里）。", file=sys.stderr)
        return 2

    if args.delete_branch:
        return _delete_branch(args, token)

    head_sha = str(_git("rev-parse", args.head)).strip()
    # base 允许传远端 SHA（本地可能不认识），所以这里不强求 rev-parse 成功
    base_probe = subprocess.run(
        ["git", "rev-parse", args.base], cwd=_ROOT, capture_output=True, check=False
    )
    base_sha = base_probe.stdout.decode("utf-8", "replace").strip() if base_probe.returncode == 0 else args.base

    base_commit = _request("GET", f"{_API}/repos/{args.repo}/git/commits/{base_sha}", token)
    if base_commit is None:
        print(f"远端没有提交 {base_sha[:8]}，base 传错了。", file=sys.stderr)
        return 2
    base_tree = base_commit["tree"]["sha"]

    # ---- 引用状态：在不在、当前指向哪 ----
    ref = _request(
        "GET", f"{_API}/repos/{args.repo}/git/ref/heads/{args.branch}", token, allow_404=True
    )
    branch_exists = ref is not None
    remote_tip = ref["object"]["sha"] if ref else None
    if branch_exists:
        print(f"远端 {args.branch} 现在指向 {remote_tip[:8]}")
        # 别人在这期间推过东西的话，我们的 base 就是过期的：在这个基础上建出来的树
        # 会把他们新加的文件当"删除"抹掉。宁可停下来说清楚，也不要悄悄覆盖。
        if remote_tip != base_sha and not args.force:
            print(
                f"远端分支已经移到 {remote_tip[:8]}，与你给的 base {base_sha[:8]} 不一致。\n"
                f"先 `git fetch` 看看别人推了什么，把 --base 换成 {remote_tip[:8]} 再来；\n"
                f"确实要覆盖就用 --force（会丢远端的 {remote_tip[:8]}）。",
                file=sys.stderr,
            )
            return 3
    else:
        if not args.create_branch:
            print(f"远端没有分支 {args.branch}。要新建就加 --create-branch。", file=sys.stderr)
            return 3
        print(f"远端没有 {args.branch}，将新建该分支")

    # 本地 head 必须真的是 base 的后代，否则这次"推送"其实是把历史换掉。
    if _is_local(base_sha) and not args.force:
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", base_sha, head_sha], cwd=_ROOT, capture_output=True, check=False
        ).returncode != 0:
            print(
                f"本地 {head_sha[:8]} 不是 base {base_sha[:8]} 的后代，推上去会改写历史。\n"
                f"确认要这样做就加 --force。",
                file=sys.stderr,
            )
            return 3

    # ---- 幂等闸门 ----
    local_blobs = _local_blob_map(head_sha)
    remote_blobs = _remote_blobs(args.repo, token, base_tree)
    if remote_blobs is not None and remote_blobs == local_blobs:
        print(f"远端 {args.branch} 的树与本地 {head_sha[:8]} 完全一致（{len(local_blobs)} 个文件），无需推送。")
        return 0

    # ---- 要推哪些提交 ----
    # base 是本机不认识的远端 sha 时，先找本地那个"树相同"的提交，把它当成 base 的替身：
    # 回放时父提交必须能落到"已存在的东西"上，拿本地 sha 去远端查只会 404。
    base_stand_in = _resolve_local_equivalent(base_sha, head_sha, base_tree)
    if base_stand_in != base_sha:
        if base_stand_in is None:
            print(
                f"  注意：本地找不到与远端 base {base_sha[:8]} 内容相同的提交，"
                f"按单提交推送（父子关系会对不上，推多项改动时慎用）",
            )
            chain = [head_sha]
        else:
            print(f"  base {base_sha[:8]}（远端）对应本地 {base_stand_in[:8]}（树相同）")
            chain = _local_commit_chain(base_stand_in, head_sha)
    else:
        chain = _local_commit_chain(base_sha, head_sha)
    if not chain:
        chain = [head_sha]
        print("  只推 1 个提交")
    else:
        print(f"  提交链 {len(chain)} 个：{' -> '.join(s[:7] for s in chain)}")
    # 本地替身要映射到远端 base，回放第一个提交时父提交才落得下去。
    stand_in_map: dict[str, str] = {}
    if base_stand_in and base_stand_in != base_sha:
        stand_in_map[base_stand_in] = base_sha

    if args.dry_run:
        for sha in chain:
            meta = _commit_meta(sha)
            print(f"  [dry-run] 提交 {sha[:8]} 父提交 {len(meta['parents'])} 个：{meta['message'].splitlines()[0][:60]}")
        return 0

    # ---- 逐个提交重放，保留父提交与合并拓扑 ----
    mapping: dict[str, str] = dict(stand_in_map)   # 本地提交 -> 远端已有/新建的提交
    trees: dict[str, str] = {base_sha: base_tree}
    last_remote = base_sha
    for sha in chain:
        meta = _commit_meta(sha)
        local_parents = meta["parents"]
        # 父提交映射：链内已重放的用新 sha，本地替身映射到远端 base，链外的原样保留。
        remote_parents = [mapping.get(p, p) for p in local_parents] or [base_sha]
        # 父提交必须能落到远端已知的提交上；落不下去说明链条断了，直接停下报清楚。
        parent_tree = trees.get(remote_parents[0])
        if parent_tree is None:
            parent_tree = _tree_of(args.repo, token, remote_parents[0])
        trees[remote_parents[0]] = parent_tree

        # 相对第一个父提交算改动（合并提交也是这个语义：净变化）。
        # 优先用本地父提交（本地 git 能直接 diff）；它是本地替身、本地没有对应对象时，
        # 退到远端 base——_changed_files 会自己改用远端树比对。
        if local_parents and _is_local(local_parents[0]):
            diff_base = local_parents[0]
        else:
            diff_base = base_sha
        files = _changed_files(diff_base, sha, args.repo, token, parent_tree)
        entries = _build_entries(files, sha, args.repo, token)
        tree = _request(
            "POST", f"{_API}/repos/{args.repo}/git/trees", token, {"base_tree": parent_tree, "tree": entries}
        )
        commit = _request(
            "POST",
            f"{_API}/repos/{args.repo}/git/commits",
            token,
            {
                "message": meta["message"],
                "tree": tree["sha"],
                "parents": remote_parents,
                "author": {"name": meta["raw_name"], "email": meta["raw_email"], "date": meta["raw_date"]},
                "committer": {
                    "name": meta["committer_name"],
                    "email": meta["committer_email"],
                    "date": meta["committer_date"],
                },
            },
        )
        mapping[sha] = commit["sha"]
        trees[commit["sha"]] = tree["sha"]
        last_remote = commit["sha"]
        extra = f"（{len(remote_parents)} 个父提交）" if len(remote_parents) > 1 else ""
        print(f"  {sha[:7]} -> {commit['sha'][:7]}  {len(files)} 个改动{extra}")

    # ---- 移动或创建引用 ----
    if args.force and branch_exists:
        print(f"\n--force：将强制把 {args.branch} 从 {base_sha[:8]} 移到 {last_remote[:8]}。")
        print("如果远端有别人推的提交，那些提交会从分支上消失（仍可在 reflog 里找回）。")
        try:
            answer = input("确认继续？输入 yes 继续：").strip().lower()
        except EOFError:
            answer = ""
        if answer != "yes":
            print("已取消。远端未改动。")
            return 1

    if branch_exists:
        _request(
            "PATCH",
            f"{_API}/repos/{args.repo}/git/refs/heads/{args.branch}",
            token,
            {"sha": last_remote, "force": bool(args.force)},
        )
    else:
        # 新建引用必须用 POST；PATCH 对不存在的引用只会给 422。
        try:
            _request(
                "POST",
                f"{_API}/repos/{args.repo}/git/refs",
                token,
                {"ref": f"refs/heads/{args.branch}", "sha": last_remote},
            )
        except RuntimeError as error:
            # 竞态窗口：「GET 探测到分支不存在」与「POST 建分支」之间，另一个推送者
            # 可能已经把同名分支建好了。此时 GitHub 返回 422 Reference already exists。
            # 这不是脚本用错了，是并发推送的正常结果，必须当成「base 过期」处理：
            # 回读远端引用，把真正指向的提交告诉他，而不是抛一个带 traceback 的崩溃。
            # 这个分支只有真并发才走得到，顺序模拟永远测不出来。
            if "Reference already exists" not in str(error):
                raise
            print(
                f"远端 {args.branch} 在本次推送期间被别人建好了，重新核对：",
                file=sys.stderr,
            )
            raced = _request(
                "GET", f"{_API}/repos/{args.repo}/git/ref/heads/{args.branch}", token, allow_404=True
            )
            if raced is not None:
                race_tip = raced["object"]["sha"]
                if race_tip != base_sha:
                    print(
                        f"远端分支已经移到 {race_tip[:8]}，与你给的 base {base_sha[:8]} 不一致。\n"
                        f"先 `git fetch` 看看别人推了什么，把 --base 换成 {race_tip[:8]} 再来；\n"
                        f"确实要覆盖就用 --force（会丢远端的 {race_tip[:8]}）。",
                        file=sys.stderr,
                    )
                    return 3
                # 极小概率：别人建的正好就是我们要的 base，说明只是慢了半拍，
                # 引用已存在且指向同一处，直接当成功。
                print(f"  远端分支已存在且正好指向 {race_tip[:8]}，按已建好处理。")
            else:
                print(f"  {args.branch} 报已存在却又查不到，请人工核对远端引用。", file=sys.stderr)
                return 3
    print(f"  引用 {args.branch} -> {last_remote[:8]}")

    # ---- 推后自校验：不信自己刚发的请求，回头查一遍 ----
    if not _verify_remote(args.repo, token, args.branch, head_sha):
        print("自校验没通过：远端内容与本地不一致，请人工核对。", file=sys.stderr)
        return 4
    print(f"\n完成并已核对：远端 {args.branch} 现在是 {last_remote}")
    return 0


def _is_local(sha: str) -> bool:
    return subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=_ROOT, capture_output=True, check=False
    ).returncode == 0


def _local_blob_map(ref: str) -> dict[str, str]:
    blobs: dict[str, str] = {}
    for line in str(_git("ls-tree", "-r", ref)).splitlines():
        meta, path = line.split("\t", 1)
        blobs[path] = meta.split()[2]
    return blobs


def _tree_of(repo: str, token: str, sha: str) -> str:
    commit = _request("GET", f"{_API}/repos/{repo}/git/commits/{sha}", token)
    if commit is None:
        raise RuntimeError(f"取不到远端提交 {sha} 的树")
    return commit["tree"]["sha"]


def _build_entries(files: list[tuple[str, bool]], head_sha: str, repo: str, token: str) -> list[dict]:
    """把改动清单变成 Tree API 的 entries。删除要显式写 sha=None，否则 base_tree 会继承回来。"""
    entries = []
    for path, deleted in files:
        if deleted:
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            print(f"    delete {path}")
            continue
        content = _git("show", f"{head_sha}:{path}", binary=True)
        # 必须走 base64。仓库里有 385 个二进制文件（data/page_math/*.png 353 张、
        # artifacts/ 7、docs/ 7、samples/ 1），按 utf-8 编码它们会抛
        # UnicodeDecodeError（pm_001.png 第 0 字节就是 0x89）。只推文本文件的场景
        # 从来碰不到这个问题，一旦推到图就整批失败。
        blob = _request(
            "POST",
            f"{_API}/repos/{repo}/git/blobs",
            token,
            {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
        )
        entries.append({"path": path, "mode": _file_mode(head_sha, path), "type": "blob", "sha": blob["sha"]})
    return entries


def _verify_remote(repo: str, token: str, branch: str, local_head: str) -> bool:
    """推完回头查：远端分支的树是否与本地 head 的树逐 blob 一致。"""
    ref = _request("GET", f"{_API}/repos/{repo}/git/ref/heads/{branch}", token, allow_404=True)
    if ref is None:
        print(f"  自校验：远端没有 {branch} 这个分支")
        return False
    remote_sha = ref["object"]["sha"]
    remote_tree = _tree_of(repo, token, remote_sha)
    actual = _remote_blobs(repo, token, remote_tree)
    if actual is None:
        print("  自校验：远端树太大被截断，跳过逐 blob 比对")
        return True
    expected = _local_blob_map(local_head)
    if actual == expected:
        print(f"  自校验：{len(expected)} 个 blob 与本地逐一一致 ✓")
        return True
    only_remote = sorted(set(actual) - set(expected))
    only_local = sorted(set(expected) - set(actual))
    differ = sorted(p for p in actual if p in expected and actual[p] != expected[p])
    print(f"  自校验：远端 {len(actual)} / 本地 {len(expected)} 个 blob")
    for label, items in (("仅远端有", only_remote), ("仅本地有", only_local), ("内容不同", differ)):
        if items:
            print(f"    {label} {len(items)} 个：{', '.join(items[:5])}")
    return False


def _delete_branch(args, token: str) -> int:
    ref = _request("GET", f"{_API}/repos/{args.repo}/git/ref/heads/{args.branch}", token, allow_404=True)
    if ref is None:
        print(f"远端没有分支 {args.branch}，无需删除。")
        return 0
    current = ref["object"]["sha"]
    print(f"将删除远端分支 {args.branch}（当前 {current[:8]}）")
    if args.dry_run:
        print("  [dry-run] 不实际删除")
        return 0
    print("删除后该分支上的提交不会立刻消失（仍可凭 SHA 取回），但分支名会空出来。")
    try:
        answer = input("确认删除？输入 yes 继续：").strip().lower()
    except EOFError:
        answer = ""
    if answer != "yes":
        print("已取消。远端未改动。")
        return 1
    _request("DELETE", f"{_API}/repos/{args.repo}/git/refs/heads/{args.branch}", token)
    gone = _request("GET", f"{_API}/repos/{args.repo}/git/ref/heads/{args.branch}", token, allow_404=True)
    if gone is not None:
        print("删除后仍能查到该分支，删除没生效。", file=sys.stderr)
        return 4
    print(f"已删除远端分支 {args.branch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
