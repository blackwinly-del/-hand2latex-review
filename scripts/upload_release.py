"""把交付包作为 Release 资产上传（不走 git 历史）。

为什么用 Release 而不是 git 提交：`dist/*.zip` 是 67 MB 二进制，
进 git 历史会让每次 clone 都背上它，而且重建一次就多一份。
`.gitignore` 里已经排除了 `dist/`，这里走 Release 才是正规做法。

Release 资产的域名是 uploads.github.com，与 git 用的 github.com:443 不是同一条，
所以 github.com 502 的时候这个通常还能用。

用法：
    # token 从环境变量读，不要写在命令行上（argv 会留在 shell 历史和进程列表里）
    export GITHUB_TOKEN=...
    python scripts/upload_release.py --repo owner/name --tag v1.0.0 --file dist/xxx.zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_API = "https://api.github.com"
_UPLOADS = "https://uploads.github.com"
_RETRIES = 5
_RETRY_DELAY = 4.0


def _request(method: str, url: str, token: str, payload: dict | None = None, raw: bytes | None = None,
             content_type: str = "application/json") -> dict:
    data = raw if raw is not None else (json.dumps(payload).encode("utf-8") if payload is not None else None)
    last: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", "application/vnd.github+json")
        if data is not None:
            request.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            last = RuntimeError(f"{method} {url} -> {error.code}\n{detail}")
            if error.code < 500:
                raise last from error
            print(f"    {error.code}，第 {attempt}/{_RETRIES} 次失败，重试")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = RuntimeError(f"{method} {url} -> 连接失败：{error}")
            print(f"    连接失败，第 {attempt}/{_RETRIES} 次，重试")
        if attempt < _RETRIES:
            time.sleep(_RETRY_DELAY * attempt)
    raise last if last else RuntimeError("未知失败")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", default=None, help="GitHub token；不传则读 GITHUB_TOKEN 环境变量")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--body", default=None)
    parser.add_argument("--file", action="append", default=[], help="要上传的文件，可重复")
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("缺少 token：请设置环境变量 GITHUB_TOKEN，或用 --token 传入（不推荐，会留在命令历史里）。", file=sys.stderr)
        return 2

    body = args.body or ""
    for path_text in args.file:
        path = Path(path_text)
        if not path.is_file():
            print(f"文件不存在：{path}")
            return 1
        body += f"\n- `{path.name}`：{path.stat().st_size / 1024 / 1024:.1f} MB，SHA256 `{_sha256(path)}`"

    existing = None
    # 已存在同 tag 就复用，避免 422
    try:
        release = _request("GET", f"{_API}/repos/{args.repo}/releases/tags/{args.tag}", token)
        existing = release
        print(f"复用已有 Release：{args.tag}")
    except RuntimeError as error:
        if "404" not in str(error):
            raise
        release = _request(
            "POST",
            f"{_API}/repos/{args.repo}/releases",
            token,
            {
                "tag_name": args.tag,
                "name": args.name or args.tag,
                "body": body.strip() or f"交付包 {args.tag}",
                "draft": bool(args.draft),
                "prerelease": False,
            },
        )
        print(f"已创建 Release：{args.tag}")

    upload_url = release["upload_url"].split("{")[0]
    for path_text in args.file:
        path = Path(path_text)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        print(f"  上传 {path.name}（{path.stat().st_size / 1024 / 1024:.1f} MB）…")
        asset = _request(
            "POST",
            f"{upload_url}?name={urllib.parse.quote(path.name)}",
            token,
            raw=path.read_bytes(),
            content_type=content_type,
        )
        print(f"    完成：{asset['browser_download_url']}")

    print(f"\nRelease 页面：{release['html_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
