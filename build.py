"""One-command Windows packaging for 研策中枢 AlphaScope.

Default:
    python build.py

Installer:
    python build.py --installer

Outputs:
    dist/AlphaScope/                         portable app directory
    installer/installer-output/*.exe         optional Inno Setup installer
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

APP_NAME = "研策中枢 AlphaScope"
ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "apps" / "web"
WEB_DIST_DIR = WEB_DIR / "dist"
DIST_DIR = ROOT / "dist" / "AlphaScope"
INSTALLER_SCRIPT = ROOT / "installer" / "setup.iss"


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print(f"[run] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(cwd), check=True)


def npm_command() -> str:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError(
            "Node.js/npm not found. Install Node.js 20+ to build the web UI."
        )
    return npm


def iscc_command() -> str | None:
    candidates = [
        shutil.which("ISCC.exe"),
        shutil.which("iscc.exe"),
        str(
            Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe"
        ),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def check_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "PyInstaller is not installed. Run: python -m pip install pyinstaller"
        ) from exc
    print(f"[ok] PyInstaller {PyInstaller.__version__}")


def clean_build() -> None:
    for directory in (ROOT / "build", ROOT / "dist"):
        if directory.exists():
            print(f"[clean] {directory}")
            shutil.rmtree(directory, ignore_errors=True)


def build_web() -> None:
    npm = npm_command()
    if not (WEB_DIR / "node_modules").exists():
        run([npm, "ci"], cwd=WEB_DIR)
    run([npm, "run", "build"], cwd=WEB_DIR)
    runtime_config = WEB_DIST_DIR / "runtime-config.js"
    runtime_config.write_text(
        "window.__ALPHASCOPE_CONFIG__ = window.__ALPHASCOPE_CONFIG__ || {};\n",
        encoding="utf-8",
    )
    print(f"[ok] Web assets: {WEB_DIST_DIR}")


def run_pyinstaller() -> None:
    check_pyinstaller()
    if not WEB_DIST_DIR.exists():
        raise RuntimeError("Web dist is missing. Run the web build first.")
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(ROOT / "alphascope.spec"),
            "--clean",
            "--noconfirm",
            "--log-level=WARN",
        ]
    )


def write_readme() -> None:
    readme = DIST_DIR / "使用说明.txt"
    readme.write_text(
        f"{APP_NAME}\n"
        "================================\n\n"
        "这是面向普通用户的一键版。\n\n"
        "启动方式:\n"
        "1. 双击 AlphaScope.exe。\n"
        "2. 程序会自动启动本地服务并打开浏览器。\n"
        "3. 使用期间请保持启动窗口打开；关闭窗口即停止本地服务。\n\n"
        "首次配置:\n"
        "1. 第一次启动会自动创建 .env。\n"
        "2. 如需使用 AI 分析，请在 .env 中填入至少一个模型 API Key。\n"
        "3. 常用最小配置: DEEPSEEK_API_KEY=your_api_key。\n\n"
        "本地地址:\n"
        "  Web: 程序启动后自动打开，默认从 http://127.0.0.1:3000 起查找可用端口。\n"
        "  API: 默认从 http://127.0.0.1:8000 起查找可用端口。\n\n"
        "数据目录:\n"
        "  data/db/       SQLite 数据库\n"
        "  data/cache/    缓存数据\n"
        "  data/reports/  分析报告\n"
        "  data/uploads/  上传文件\n",
        encoding="utf-8",
    )
    print(f"[ok] {readme}")


def copy_runtime_files() -> None:
    if not DIST_DIR.exists():
        raise RuntimeError(f"PyInstaller output does not exist: {DIST_DIR}")

    env_example = ROOT / ".env.example"
    if env_example.exists():
        shutil.copy2(env_example, DIST_DIR / ".env.example")

    for relative in (
        "data",
        "data/db",
        "data/cache",
        "data/cache/fundamentals",
        "data/cache/chroma_db",
        "data/reports",
        "data/reports/archive",
        "data/uploads",
        "data/logs",
    ):
        (DIST_DIR / relative).mkdir(parents=True, exist_ok=True)

    # 预置种子行情(常用股近1年日线,无任何 key);首次启动后会自动补到最新
    seed_db = ROOT / "seed" / "ai_finance.db"
    if seed_db.exists():
        shutil.copy2(seed_db, DIST_DIR / "data" / "db" / "ai_finance.db")
        print(f"[ok] Seeded price data -> {DIST_DIR / 'data' / 'db' / 'ai_finance.db'}")
    else:
        print("[warn] seed/ai_finance.db 不存在,发布版将无预置行情(可先跑 scripts/build_seed_db.py)")

    write_readme()

    # 防御:发布目录绝不携带真实 .env(曾因手工运行遗留进 dist/),只允许 .env.example 占位
    stray_env = DIST_DIR / ".env"
    if stray_env.exists():
        stray_env.unlink()
        print(f"[warn] 已删除误入发布目录的 {stray_env}(发布物只允许 .env.example 占位)")


def build_installer() -> Path | None:
    iscc = iscc_command()
    if not iscc:
        print(
            "[skip] Inno Setup not found. Install Inno Setup 6 to create a single setup exe."
        )
        return None
    run([iscc, str(INSTALLER_SCRIPT)], cwd=ROOT / "installer")
    output_dir = ROOT / "installer" / "installer-output"
    installers = sorted(
        output_dir.glob("AlphaScope-Setup-*.exe"), key=lambda p: p.stat().st_mtime
    )
    return installers[-1] if installers else None


def portable_zip() -> Path:
    archive_base = ROOT / "dist" / "AlphaScope-portable"
    archive_path = Path(
        shutil.make_archive(str(archive_base), "zip", root_dir=DIST_DIR)
    )
    print(f"[ok] Portable zip: {archive_path}")
    return archive_path


def print_summary(installer: Path | None, make_zip: bool) -> None:
    exe_path = DIST_DIR / "AlphaScope.exe"
    size_mb = sum(f.stat().st_size for f in DIST_DIR.rglob("*") if f.is_file()) / (
        1024 * 1024
    )

    print()
    print("=" * 60)
    print("  Build complete")
    print("=" * 60)
    print(f"  Portable directory: {DIST_DIR}")
    print(f"  Main program:       {exe_path}")
    print(f"  Size:               {size_mb:.1f} MB")
    if installer:
        print(f"  Installer:          {installer}")
    elif make_zip:
        print("  Installer:          skipped because Inno Setup was not found")
    print()
    print("  Test locally:")
    print(f"    {exe_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Build {APP_NAME} for Windows")
    parser.add_argument(
        "--skip-web", action="store_true", help="reuse existing apps/web/dist"
    )
    parser.add_argument(
        "--installer", action="store_true", help="also build Inno Setup installer"
    )
    parser.add_argument("--zip", action="store_true", help="also create a portable zip")
    parser.add_argument(
        "--no-clean", action="store_true", help="do not remove build/dist first"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print()
    print("=" * 60)
    print(f"  {APP_NAME} packaging")
    print("=" * 60)
    print()

    try:
        if not args.no_clean:
            clean_build()
        if not args.skip_web:
            build_web()
        run_pyinstaller()
        copy_runtime_files()
        if args.zip:
            portable_zip()
        installer = build_installer() if args.installer else None
        print_summary(installer, args.installer)
    except Exception as exc:
        print(f"\n[error] {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
