import os
import re
import shutil
import subprocess
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TECTONIC_DIR = _PROJECT_ROOT / "tools" / "tectonic"


def _find_tectonic() -> Path | None:
    """定位 tectonic 可执行文件。

    查找顺序：项目内置（Windows 为 tectonic.exe，其他平台无扩展名；两个名字
    都会兼容探测，避免从别的平台拷贝过来的目录用不了）→ 系统 PATH。
    都找不到返回 None，由 compile_tex 给出明确的安装提示。
    """
    preferred = "tectonic.exe" if os.name == "nt" else "tectonic"
    fallback = "tectonic" if os.name == "nt" else "tectonic.exe"
    for name in (preferred, fallback):
        candidate = _TECTONIC_DIR / name
        if candidate.is_file():
            return candidate
    found = shutil.which("tectonic")
    if found:
        return Path(found)
    return None


def parse_compile_errors(log: str) -> list[dict]:
    errors = []
    for match in re.finditer(r"(?m)^(?!warning:)(?:error:\s*)?([^\n]*?\.tex):(\d+):\s*(.*)$", log):
        errors.append({"line": int(match.group(2)), "message": match.group(3)})
    if errors:
        return errors

    match = re.search(r"(?m)^error:\s*(?:at\s+)?line\s+(\d+)(?::\s*)?(.*)$", log)
    if match:
        return [{"line": int(match.group(1)), "message": match.group(2)}]
    match = re.search(r"(?m)^error:\s*(.*)$", log)
    if match:
        return [{"line": None, "message": match.group(1)}]
    return []


# ---------------------------------------------------------------------------
# 结构化诊断：行号 + 上下文片段
#
# 为什么需要另写一套，而不是给 parse_compile_errors 加字段：
#
# 1. parse_compile_errors 的正则是 (?!warning:)，**warning 类问题根本不进来**。
#    实测 `Missing character`（字体里没有某个符号）返回码是 0、编译"成功"，
#    只在 stderr 里留一条 warning。也就是 PDF 已经生成、页面看起来正常，
#    但某个符号悄悄变成了空白——这正是最需要提示用户去核对的一类问题，
#    而它一条都不会出现在 errors 里，全靠前端自己扫日志。
# 2. 老函数被测试和其他调用方按 "line/message" 两键精确断言过，
#    加字段会破坏既有契约。所以新能力走新函数、新键名。
# 3. Tectonic 的消息体经常是空的。实测一条缺字警告长这样：
#        warning: b.tex:4: 
#        Missing character: There is no ... (U+20BB7) in font ...;!
#    前缀那行只有"文件:行号:"，冒号后面什么都没有，真正的原因在**下一行**。
#    只按行做正则匹配，拿到的是空消息——用户看到的就是一行没有任何信息的红字。
# 4. Tectonic 因为 rerun 会把同一条警告打两遍（实测 b.tex 的缺字警告出现
#    两次，中间夹着 note: Rerunning TeX）。不去重就会重复提示同一个问题。
# ---------------------------------------------------------------------------

_MAX_DIAGNOSTICS = 50
# 解析阶段先留足余量：缺字警告是**逐字符**一条的，实测一个小文件能出 20 多条。
# 如果边解析边按 50 截断，一个满屏缺字警告的文档会把后面真正的语法错误挤掉，
# 用户看到 50 条"符号不存在"却看不到"Undefined control sequence"。
_MAX_RAW_DIAGNOSTICS = 400
_CONTEXT_RADIUS = 2

# "error: main.tex:4: xxx" / "warning: b.tex:12: " / "error: line 9: xxx"
# 注意文件名部分：Tectonic 有时**不带扩展名**。实测 \input{page_1} 出错时打的是
#   warning: page_1:1: Missing character: ...
# 只认 .tex 会让这类消息整条漏掉，所以扩展名做成可选的。
_DIAG_HEAD = re.compile(
    r"^(?P<sev>error|warning):\s*"
    r"(?:(?P<file>[^\s:][^\n:]*?):(?P<line>\d+):"
    r"|(?:at\s+)?line\s+(?P<line2>\d+)\s*:?)\s*(?P<rest>.*)$"
)
# 没有定位信息的普通 warning/error 前缀（多为上一条的补充说明）
_DIAG_BARE = re.compile(r"^(?P<sev>error|warning):\s*(?P<rest>.*)$")
# XeTeX 引擎自己打的感叹号块
_TEX_BANG = re.compile(r"^!\s*(?P<msg>.+?)\s*$")
# "l.4 This line has \undefinedcmd" —— 断点前的源码片段
_TEX_LNUM = re.compile(r"^l\.(?P<line>\d+)\s?(?P<text>.*)$")
_UNICODE_CODE = re.compile(r"\(U\+(?P<hex>[0-9A-Fa-f]{4,6})\)|\(0x(?P<hex2>[0-9A-Fa-f]+)\)")
# 缺字消息里那个字符本身是打不出来的，日志里会变成一串 U+FFFD 替换符。
# 原样透出去，用户看到的就是 "There is no ���� (U+20BB7)" 这种没法读的东西。
_GLYPH_MOJIBAKE = re.compile(r"(There is no)\s*\ufffd+\s*(\((?:U\+|0x)[0-9A-Fa-f]+\))?")


def _clean_glyph_message(message: str, code: str | None) -> str:
    """把缺字警告里打不出来的字符换成一个可读的占位，保留码位。"""
    if "Missing character" not in message and "could not represent" not in message:
        return message
    codepoint = f"U+{code}" if code else ""
    cleaned = _GLYPH_MOJIBAKE.sub(r"\1 这个字符", message)
    cleaned = cleaned.replace("\ufffd", "")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if codepoint and codepoint not in cleaned:
        cleaned = f"{cleaned} (码位 {codepoint})"
    return cleaned


def _line_context(tex: str | None, line: int | None, radius: int = _CONTEXT_RADIUS) -> list[dict]:
    """取主 tex 中目标行前后各 radius 行，供前端直接展示，省得用户自己翻日志。"""
    if not tex or not line or line < 1:
        return []
    lines = tex.splitlines()
    if line > len(lines):
        return []
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    return [
        {"line": number, "text": lines[number - 1].rstrip(), "is_target": number == line}
        for number in range(start, end + 1)
    ]


def _is_main_file(name: str | None, main_name: str | None = None) -> bool:
    """判断诊断里的文件名是不是正在编译的那个主文件。

    Tectonic 报主文件时写 `main.tex`，报子文件时可能写 `page_1`（没有扩展名）。
    两种情况都要认得，否则行号会被错误地当成"可以直接跳"。

    main_name 由调用方传入实际编译的文件名（compile_tex 传 tex_path.name）。
    不能硬编码 "main"：单张图的调试、用户直接编译别的文件名时，主文件就叫别的
    名字，硬编码会把它当成子文件，反而丢掉本来正确的行号。
    """
    if not name:
        return False

    def _stem(raw: str) -> str:
        base = os.path.basename(raw.replace("\\", "/"))
        return base[:-4] if base.lower().endswith(".tex") else base

    if main_name and _stem(name).lower() == _stem(main_name).lower():
        return True
    return _stem(name).lower() in {"main", "hand2latex", "document"}


def _locate_by_snippet(tex: str | None, snippet: str | None) -> int | None:
    """用 Tectonic 回显的源码片段在 tex 里反查行号。

    为什么需要反查：`file:line` 里的文件名不一定是 main.tex。多页任务会把每页
    写成 page_N.tex 再 \\input 进来，此时行号是相对那个子文件的，前端却按
    main.tex 的行号跳转，会跳到完全无关的位置。用源码片段反查得到的是
    "这段文字在 main.tex 的哪一行"，才是用户真正要跳过去改的地方。

    只在**唯一匹配**时才采信：同一段文字出现多次时，宁可不给行号让对方按
    片段自己找，也不能指到一个错的位置上。
    """
    text = (snippet or "").strip()
    if not tex or len(text) < 3:
        return None
    lines = tex.splitlines()
    hits = [index + 1 for index, content in enumerate(lines) if text in content]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        return None
    # 片段包含 TeX 断点处的多余空白时整体匹配不上，退一步用首段长词试一次。
    words = [word for word in text.split() if len(word) >= 4]
    if not words:
        return None
    hits = [index + 1 for index, content in enumerate(lines) if words[0] in content]
    return hits[0] if len(hits) == 1 else None


def parse_compile_diagnostics(log: str, tex: str | None = None, *, main_name: str | None = None) -> list[dict]:
    """把编译日志解析成带行号和上下文的结构化诊断。

    返回的每一条都包含：severity（error/warning）、line（可能为 None）、
    message（已补齐跨行消息体）、file、snippet（编译器回显的源码片段）、
    code（缺字问题的 Unicode 码位）、context（主 tex 中该行前后几行）、
    located_by（行号来源：snippet 反查 / reported 编译器给的 / subfile 子文件相对行号）。
    """
    diagnostics: list[dict] = []
    seen: set[tuple] = set()
    current: dict | None = None

    def push(item: dict) -> dict | None:
        """去重后追加。同一问题因 rerun 被重复打印时只保留第一条。"""
        key = (item["severity"], item.get("file"), item.get("line"), item["message"])
        if key in seen:
            return None
        seen.add(key)
        if len(diagnostics) >= _MAX_RAW_DIAGNOSTICS:
            return None
        diagnostics.append(item)
        return item

    for raw in log.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue

        head = _DIAG_HEAD.match(stripped)
        if head:
            line = head.group("line") or head.group("line2")
            current = {
                "severity": head.group("sev"),
                "file": head.group("file"),
                "line": int(line) if line else None,
                "message": head.group("rest").strip(),
                "snippet": None,
                "code": None,
                "hint": None,
            }
            current = push(current) or current
            continue

        bang = _TEX_BANG.match(stripped)
        if bang:
            message = bang.group("msg").strip()
            # 前面已经有 "error: main.tex:4: Undefined control sequence"，
            # 引擎这块是同一件事的另一种说法，只用来补片段，不新增条目。
            if current is not None and current["severity"] == "error" and (
                not current["message"] or current["message"].rstrip(".") == message.rstrip(".")
            ):
                current["message"] = current["message"] or message
            else:
                current = push({
                    "severity": "error",
                    "file": None,
                    "line": None,
                    "message": message,
                    "snippet": None,
                    "code": None,
                    "hint": None,
                }) or current
            continue

        lnum = _TEX_LNUM.match(stripped)
        if lnum and current is not None:
            current["snippet"] = lnum.group("text").strip()
            if current["line"] is None:
                current["line"] = int(lnum.group("line"))
            continue

        bare = _DIAG_BARE.match(stripped)
        if bare:
            message = bare.group("rest").strip()
            if not message:
                continue
            if current is None:
                continue
            # 缺字警告的第二、三行：一条重复描述 + 一条修复建议。
            if "you may need to load" in message or "choose a different font" in message:
                current["hint"] = current["hint"] or (
                    "这个符号需要用 fontspec 换一个包含它的字体，或者改用 LaTeX 命令写法"
                )
                continue
            if "could not represent character" in message:
                if current["code"] is None:
                    code = _UNICODE_CODE.search(message)
                    if code:
                        current["code"] = (code.group("hex") or code.group("hex2") or "").upper()
                continue
            # 引擎没给 "文件:行号:" 前缀时的兜底：挂到当前条目上。
            continue

        # 不以 error:/warning: 开头的行，多半是上一条被拆开的消息体。
        if current is not None and not current["message"]:
            current["message"] = stripped
            code = _UNICODE_CODE.search(stripped)
            if code and current["code"] is None:
                current["code"] = (code.group("hex") or code.group("hex2") or "").upper()

    result = []
    for item in diagnostics:
        if item["code"] is None and item["message"]:
            code = _UNICODE_CODE.search(item["message"])
            if code:
                item["code"] = (code.group("hex") or code.group("hex2") or "").upper()
        # 行号优先级：主 tex 唯一反查 > 编译器给的行号 > None
        #
        # 为什么要区分是否"同一个文件"：多页任务把每页写成 page_N.tex 再 \input
        # 进 main.tex。此时 Tectonic 报的是 `page_1:2:`，这个 2 是**子文件里**的
        # 第 2 行，而前端 jumpToLine 是按 main.tex 的行号跳的。直接采信会把用户
        # 送到 main.tex 第 2 行（\documentclass 附近），完全无关。能反查到主文件
        # 的真实行号就反查；反查不到也标出来源，让前端不要盲跳。
        located = _locate_by_snippet(tex, item["snippet"])
        if located is not None:
            item["line"] = located
            item["located_by"] = "snippet"
        elif item["line"] is not None and item["file"] and not _is_main_file(item["file"], main_name):
            item["located_by"] = "subfile"
        elif item["line"] is not None:
            item["located_by"] = "reported"
        else:
            item["located_by"] = None
        item["context"] = _line_context(tex, item["line"])
        if not item["message"]:
            item["message"] = item["snippet"] or "编译器没有给出具体原因"
        item["message"] = _clean_glyph_message(item["message"], item["code"])
        result.append(item)

    # 同一行的多个缺字合并成一条。
    #
    # 实测一行中文里有 6 个字符当前字体没有，日志就是 6 条几乎一样的
    # "Missing character"，界面上一列排下来完全分不清哪条是哪条。合并后是
    # "第 4 行有 6 个字符缺字：U+8FD9、U+91CC……"，一行就能看完。
    # 注意只合并 warning 级的缺字，error 一条都不能合并——每条错误的行号和
    # 原因都可能不同，合并会把信息抹掉。
    merged: list[dict] = []
    glyph_index: dict[tuple, dict] = {}
    for item in result:
        if item["severity"] == "warning" and "Missing character" in item["message"]:
            key = (item["line"], item["located_by"], item["file"])
            existing = glyph_index.get(key)
            if existing is None:
                item = dict(item)
                item["codes"] = [item["code"]] if item["code"] else []
                item["glyph_count"] = 1
                glyph_index[key] = item
                merged.append(item)
            else:
                if item["code"] and item["code"] not in existing["codes"]:
                    existing["codes"].append(item["code"])
                existing["glyph_count"] = len(existing["codes"])
            continue
        merged.append(item)

    for item in merged:
        if item.get("glyph_count", 0) > 1:
            codes = "、".join(f"U+{code}" for code in item["codes"])
            item["message"] = f"这一行有 {item['glyph_count']} 个字符在当前字体里不存在：{codes}"
            item["code"] = item["codes"][0] if item["codes"] else None

    result = merged

    # error 一定排在 warning 前面，同类内部保持日志原本的先后（行号顺序）。
    # 原因同上：缺字警告能刷几十条，真正的语法错误如果排在后面就会被截断掉。
    result.sort(key=lambda item: 0 if item["severity"] == "error" else 1)
    return result[:_MAX_DIAGNOSTICS]


def compile_tex(tex_path: str | Path, *, timeout: int = 120, include_diagnostics: bool = True) -> dict:
    tex_path = Path(tex_path).resolve()
    if not tex_path.is_file():
        raise ValueError("tex file does not exist")

    pdf_path = tex_path.with_suffix(".pdf")
    try:
        pdf_path.unlink(missing_ok=True)
        tectonic = _find_tectonic()
        if tectonic is None:
            raise RuntimeError(
                "tectonic is not installed: expected tools/tectonic/"
                f"{'tectonic.exe' if os.name == 'nt' else 'tectonic'} in the project, "
                "or tectonic on PATH"
            )
        completed = subprocess.run(
            [str(tectonic), str(tex_path)],
            cwd=tex_path.parent,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"tectonic could not compile the document: {error}") from error

    log = (completed.stdout or "") + (completed.stderr or "")
    success = completed.returncode == 0 and pdf_path.is_file()
    result = {
        "success": success,
        "pdf_path": str(pdf_path) if success else None,
        "log": log,
        "errors": parse_compile_errors(log),
        "returncode": completed.returncode,
    }
    if include_diagnostics:
        try:
            source = tex_path.read_text(encoding="utf-8")
        except OSError:
            source = None
        result["diagnostics"] = parse_compile_diagnostics(log, source, main_name=tex_path.name)
    return result
