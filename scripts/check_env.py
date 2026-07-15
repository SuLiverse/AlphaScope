"""环境检查脚本 — 验证本地运行所需条件"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_PYTHON_MIN = (3, 11)
REQUIRED_PYTHON_MAX = (3, 13)
REQUIRED_NODE = 18

# Windows 终端 ANSI 颜色支持
if sys.platform == "win32":
    import os

    os.system("")  # 启用 ANSI 转义序列


def _check(name: str, ok: bool, detail: str = "") -> bool:
    tag = "\033[32m[OK]\033[0m" if ok else "\033[31m[FAIL]\033[0m"
    msg = f"  {tag} {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return ok


def _cmd_version(cmd: str) -> str | None:
    try:
        r = subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            shell=sys.platform == "win32",
        )
        return r.stdout.strip()
    except Exception:
        return None


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def check_python() -> bool:
    v = sys.version_info
    current = (v.major, v.minor)
    ok = REQUIRED_PYTHON_MIN <= current < REQUIRED_PYTHON_MAX
    return _check(
        "Python",
        ok,
        (
            f"{v.major}.{v.minor}.{v.micro} "
            f"(需要 >= {REQUIRED_PYTHON_MIN[0]}.{REQUIRED_PYTHON_MIN[1]}"
            f", < {REQUIRED_PYTHON_MAX[0]}.{REQUIRED_PYTHON_MAX[1]})"
        ),
    )


def check_node() -> bool:
    ver = _cmd_version("node")
    if not ver:
        return _check("Node.js", False, "未安装")
    try:
        # node --version 输出格式: "v24.15.0"
        version_str = ver.lstrip("v").split()[0]
        major = int(version_str.split(".")[0])
    except (IndexError, ValueError):
        major = 0
    ok = major >= REQUIRED_NODE
    return _check("Node.js", ok, f"{ver} (需要 >= {REQUIRED_NODE})")


def check_npm() -> bool:
    ver = _cmd_version("npm")
    ok = ver is not None
    return _check("npm", ok, ver or "未安装")


def check_deps(auto_fix: bool = False, include_streamlit: bool = False) -> bool:
    missing = []
    required_modules = ["fastapi", "openai", "uvicorn"]
    if include_streamlit:
        required_modules.extend(["streamlit", "plotly"])
    for mod in required_modules:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)

    if not missing:
        return _check("Python 依赖", True, "已安装")

    if auto_fix:
        print(f"  正在安装缺失依赖: {', '.join(missing)}")
        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-e",
                    ".[api,streamlit]" if include_streamlit else ".[api]",
                ],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
            )
            return _check("Python 依赖", True, "已自动安装")
        except subprocess.CalledProcessError as e:
            print(f"  安装失败: {e}")
            return _check("Python 依赖", False, f"安装失败，缺少: {', '.join(missing)}")
    else:
        return _check("Python 依赖", False, f"缺少: {', '.join(missing)}")


def check_frontend_deps(auto_fix: bool = False) -> bool:
    node_modules = PROJECT_ROOT / "apps" / "web" / "node_modules"
    if node_modules.exists():
        return _check("前端依赖", True, "已安装")

    if auto_fix:
        print("  正在安装前端依赖...")
        try:
            subprocess.run(
                ["npm", "install"],
                cwd=PROJECT_ROOT / "apps" / "web",
                check=True,
                capture_output=True,
                shell=sys.platform == "win32",
            )
            return _check("前端依赖", True, "已自动安装")
        except subprocess.CalledProcessError:
            return _check("前端依赖", False, "安装失败")
    else:
        return _check("前端依赖", False, "未安装")


def check_env_file(auto_create: bool = False) -> bool:
    env = PROJECT_ROOT / ".env"
    example = PROJECT_ROOT / ".env.example"
    if env.exists():
        return _check(".env 文件", True, "存在")

    if auto_create and example.exists():
        import shutil

        shutil.copy(example, env)
        return _check(".env 文件", True, "已从 .env.example 创建")

    if example.exists():
        return _check(".env 文件", False, "不存在，请执行: copy .env.example .env")
    return _check(".env 文件", False, "不存在且无 .env.example 模板")


def check_ports(include_streamlit: bool = False) -> bool:
    ports = [3000, 8000, 8501]
    if not include_streamlit:
        ports.remove(8501)
    blocked = [p for p in ports if not _port_free(p)]
    ok = len(blocked) == 0
    detail = f"被占用: {blocked} (运行 stop_local.ps1 释放)" if blocked else f"{ports} 均可用"
    return _check("端口", ok, detail)


def check_dirs(auto_create: bool = False) -> bool:
    required = ["data/db", "data/cache", "data/reports", "data/uploads", "data/logs"]
    missing = [d for d in required if not (PROJECT_ROOT / d).is_dir()]

    if not missing:
        return _check("数据目录", True, "齐全")

    if auto_create:
        for d in missing:
            (PROJECT_ROOT / d).mkdir(parents=True, exist_ok=True)
        return _check("数据目录", True, f"已创建: {', '.join(missing)}")
    else:
        return _check("数据目录", False, f"缺少: {', '.join(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="研策中枢 AlphaScope 环境检查")
    parser.add_argument("--fix", action="store_true", help="自动修复问题")
    parser.add_argument(
        "--with-streamlit",
        action="store_true",
        help="额外检查可选 Streamlit 调试台依赖和端口",
    )
    args = parser.parse_args()

    print("研策中枢 AlphaScope 环境检查\n")
    checks = [
        check_python(),
        check_node(),
        check_npm(),
        check_deps(auto_fix=args.fix, include_streamlit=args.with_streamlit),
        check_frontend_deps(auto_fix=args.fix),
        check_env_file(auto_create=args.fix),
        check_ports(include_streamlit=args.with_streamlit),
        check_dirs(auto_create=args.fix),
    ]
    passed = sum(checks)
    total = len(checks)
    print(f"\n结果: {passed}/{total} 通过")
    if all(checks):
        print("\033[32m可以启动！\033[0m")
        return 0
    if args.fix:
        print("\033[33m部分问题无法自动修复，请手动处理。\033[0m")
    else:
        print("\033[31m请先修复上述问题再启动，或使用 --fix 自动修复。\033[0m")
    return 1


if __name__ == "__main__":
    sys.exit(main())
