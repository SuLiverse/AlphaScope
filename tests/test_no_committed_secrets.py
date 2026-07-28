"""守门员测试：git 跟踪的文档/配置文本中不得出现真实密钥赋值。

背景：AUDIT-2026-07-01.md 曾误提交 AI_FINANCE_MASTER_KEY 明文值
（见 plans/001-secret-exposure-cleanup-and-rotation.md）。

规则：对 git ls-files 枚举到的文档/配置类文本
（.md/.txt/.yaml/.yml/.js/.example），扫描形如
``(_API_KEY|_API_SECRET|MASTER_KEY|_TOKEN)=<16+ 非空白字符>`` 的字面赋值。
排除 `.env.example`、占位值（`your_*` / `<` / `$` 开头、含 `...` 的掩码、
纯 `x`/`*` 占位）以及 `os.environ.get(...)` 等代码取值形态。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 只扫文档/配置类文本后缀中的字面赋值；.py 等代码文件不扫
SCANNED_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".js", ".example"}

ASSIGNMENT_RE = re.compile(
    r"(?:_API_KEY|_API_SECRET|MASTER_KEY|_TOKEN)\s*=\s*\"?'?(\S{16,})\"?'?"
)


def _is_placeholder(value: str) -> bool:
    """识别占位符/掩码/代码形态，避免误报。"""
    v = value.strip().strip("\"'")
    if not v:
        return True
    if v.startswith(("your_", "your-", "<", "$", "#")):
        return True
    if "..." in v:  # 掩码形态，如 sk-a...x9Zz
        return True
    if "(" in v:  # 代码取值形态，如 os.environ.get("X")
        return True
    if re.fullmatch(r"[xX*]+", v):  # 纯占位
        return True
    return False


def find_secret_assignments(text: str) -> list[tuple[int, str]]:
    """返回 [(行号, 命中的行)]，只计真实赋值，不计占位符。"""
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in ASSIGNMENT_RE.finditer(line):
            if not _is_placeholder(match.group(1)):
                hits.append((lineno, line.strip()))
                break
    return hits


def _tracked_text_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    files = []
    for rel in out.splitlines():
        p = Path(rel)
        if p.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        if rel.endswith(".env.example"):  # 模板文件，只含占位
            continue
        files.append(rel)
    return files


def test_no_committed_secret_assignments() -> None:
    findings: list[str] = []
    for rel in _tracked_text_files():
        path = REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in find_secret_assignments(text):
            findings.append(f"{rel}:{lineno}: {line}")
    assert not findings, "跟踪文件中发现疑似密钥赋值：\n" + "\n".join(findings)


def test_scanner_detects_fake_secret() -> None:
    """测测试：构造含假 key 的文本，验证扫描器本身能命中。"""
    fake = "TEST_MASTER_KEY=" + "A" * 32
    hits = find_secret_assignments("# doc\n" + fake + "\n")
    assert len(hits) == 1 and hits[0][0] == 2


def test_scanner_ignores_placeholders() -> None:
    """占位符、掩码与代码取值形态不应命中。"""
    text = "\n".join(
        [
            "DEEPSEEK_API_KEY=your_api_key_here_please",
            "TEST_MASTER_KEY=<your-master-key-here>",
            'TEST_API_SECRET="sk-a...x9Zz"',
            "TEST_TOKEN=xxxxxxxxxxxxxxxxxxxx",
            "TEST_MASTER_KEY = os.environ.get('TEST_MASTER_KEY')",
        ]
    )
    assert find_secret_assignments(text) == []
