"""桌面窗口外壳：把工作台包成一个独立的原生应用窗口。

设计取舍（为什么不用 Electron / PyQt / pywebview 硬依赖）：

- **不引入重依赖**：随包运行时只有 Web 栈，没有 pip，装不了 pywebview。
  为了一个窗口去塞几十 MB 的框架，对"双击就能用"是负收益。
- **优先用系统自带的 WebView2**：Windows 10/11 都有 Microsoft Edge，
  `msedge --app=URL` 会开一个**没有地址栏、没有标签页、没有书签栏**的独立窗口，
  任务栏图标独立，看起来就是个桌面应用。零安装、零体积。
- **装了 pywebview 就优先用它**：有真原生窗口句柄、能自定义标题栏和最小尺寸，
  体验更好。但它只是"可选增强"，缺了不影响使用。

这个模块**不碰识别内核**：它只负责起服务、开窗口、退出时收尾。
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PORT = 8760
_APP_TITLE = "Hand2LaTeX 智能工作台"
_WINDOW_SIZE = (1560, 980)
_MIN_SIZE = (1120, 700)


# ---------------------------------------------------------------------------
# 端口与健康检查
# ---------------------------------------------------------------------------
def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _pick_port(preferred: int | None = None) -> int:
    """优先用偏好端口，被占用就往后找；全满则交给系统分配。"""
    start = preferred or int(os.environ.get("WORKBENCH_PORT") or _DEFAULT_PORT)
    for port in range(start, start + 40):
        if _port_available(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_ready(url: str, timeout_seconds: float = 45.0) -> bool:
    """等服务真的能响应 /api/status，再开窗口——否则用户会看到一片白。"""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/status", timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(0.25)
    return False


# ---------------------------------------------------------------------------
# 服务进程
# ---------------------------------------------------------------------------
def _start_server(port: int) -> subprocess.Popen:
    """在后台起 uvicorn。

    用当前解释器的 `-m uvicorn`，而不是 shell 里拼命令：
    路径有中文、有空格时只有这种方式不会出事。
    """
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    creationflags = 0
    if os.name == "nt":
        # 桌面壳不该额外弹一个黑色控制台窗口。
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "workbench.app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def _stop_server(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=8)
    except (subprocess.TimeoutExpired, OSError):
        try:
            process.kill()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 窗口后端
# ---------------------------------------------------------------------------
def _find_edge() -> str | None:
    """找系统自带的 Edge（Windows 上一定有，它就是 WebView2 的宿主）。"""
    candidates = []
    for env_name in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    for name in ("msedge", "microsoft-edge", "chromium", "google-chrome", "chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _open_app_window_edge(url: str) -> bool:
    """用 Edge 的 --app 模式开独立窗口：无地址栏、无标签栏，任务栏独立。"""
    edge = _find_edge()
    if not edge:
        return False
    # 单独的用户数据目录：不污染用户日常浏览器的标签页和登录态，
    # 也避免"已有 Edge 在跑"时 --app 被合并进普通窗口。
    profile = Path(os.environ.get("LOCALAPPDATA") or _PROJECT_ROOT) / "Hand2LaTeX" / "window-profile"
    try:
        profile.mkdir(parents=True, exist_ok=True)
    except OSError:
        profile = _PROJECT_ROOT / "artifacts" / "window-profile"
        profile.mkdir(parents=True, exist_ok=True)

    width, height = _WINDOW_SIZE
    args = [
        edge,
        f"--app={url}",
        f"--window-size={width},{height}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
        "--disable-background-mode",
        # 桌面窗口的观感：不要滚动条挤在右边、不要默认大写菜单。
        "--force-device-scale-factor=1",
    ]
    try:
        subprocess.Popen(args, close_fds=True)
        return True
    except OSError:
        return False


def _run_pywebview(url: str) -> bool:
    """装了 pywebview 就用它：真原生窗口，能设最小尺寸和标题。"""
    try:
        import webview  # noqa: PLC0415 - 可选依赖，只有装了才走到这里
    except ImportError:
        return False
    try:
        window = webview.create_window(
            _APP_TITLE,
            url,
            width=_WINDOW_SIZE[0],
            height=_WINDOW_SIZE[1],
            min_size=_MIN_SIZE,
            text_select=True,
        )
        webview.start()
        del window
        return True
    except Exception:  # noqa: BLE001 - 窗口起不来就退回 Edge，不让整个程序挂掉
        return False


def _open_browser(url: str) -> None:
    """最后的兜底：用系统默认浏览器打开，至少让人能用。"""
    import webbrowser  # noqa: PLC0415 - 只有走到兜底才需要

    webbrowser.open(url)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def run(port: int | None = None, headless_seconds: float = 0.0, attach: str | None = None) -> int:
    """启动桌面工作台。

    headless_seconds > 0 时不打开任何窗口，只把服务跑指定秒数后退出——
    给自动化验收用（CI、无头浏览器截图）。

    attach 给一个已经在跑的地址时，只开窗口、不起服务、也不在退出时停服务——
    用户重复双击时用它挂到已有的那个窗口上，避免起第二个服务。
    """
    if attach:
        if not _wait_ready(attach, timeout_seconds=10.0):
            # 调用方（launch.ps1）会据此回退到"新起一个服务"。
            print(f"目标地址没有响应：{attach}", file=sys.stderr)
            return 2
        print(f"{_APP_TITLE} 已在运行：{attach}")
        if _open_app_window_edge(attach):
            return 0
        _open_browser(attach)
        return 0

    chosen = _pick_port(port)
    url = f"http://127.0.0.1:{chosen}"

    server = _start_server(chosen)
    try:
        if not _wait_ready(url):
            print(f"服务在 45 秒内没有就绪：{url}", file=sys.stderr)
            return 1

        if headless_seconds > 0:
            print(f"服务已就绪：{url}（无窗口模式，{headless_seconds:.0f} 秒后退出）")
            time.sleep(headless_seconds)
            return 0

        print(f"{_APP_TITLE} 已启动：{url}")
        print("关闭窗口即可退出；也可以直接关掉这个窗口。")

        if _run_pywebview(url):
            return 0
        if _open_app_window_edge(url):
            # Edge --app 是子进程，父进程要活着否则窗口可能一起没。
            # 这里等子进程不可行（拿不到句柄），用"服务活着就继续挂着"的方式。
            try:
                while server.poll() is None:
                    time.sleep(1.0)
            except KeyboardInterrupt:
                pass
            return 0

        _open_browser(url)
        print("没有找到 Edge，已用默认浏览器打开。建议装 Microsoft Edge 获得独立窗口体验。", file=sys.stderr)
        try:
            while server.poll() is None:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        _stop_server(server)


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415 - 只有命令行入口需要

    parser = argparse.ArgumentParser(description="以桌面窗口方式启动 Hand2LaTeX 工作台")
    parser.add_argument("--port", type=int, default=None, help="固定端口（默认 8760，被占用会自动往后找）")
    parser.add_argument("--headless-seconds", type=float, default=0.0, help="只起服务不开窗口，指定秒数后退出（自动化用）")
    parser.add_argument("--no-window", action="store_true", help="等价于 --headless-seconds 的一个很长值，仅供调试")
    parser.add_argument("--attach", default=None, help="连到已在运行的服务地址（只开窗口，不起也不停服务）")
    args = parser.parse_args(argv)
    seconds = args.headless_seconds
    if args.no_window and seconds <= 0:
        seconds = 3600.0
    return run(port=args.port, headless_seconds=seconds, attach=args.attach)


if __name__ == "__main__":
    raise SystemExit(main())


# 让 `python -m workbench.desktop` 和多线程场景都不会因为缺 main 而报错。
_ = threading
