"""Plan 015 防回归: 模块 import 不得再静默全进程 warnings。

历史问题: backend/news_data.py、backend/fundamentals.py、backend/fund_flow.py、
backend/providers/akshare_provider.py 曾在 import 时执行裸的
warnings.filterwarnings("ignore"), 污染整个进程的警告面
(掩盖 pandas 3.0 迁移警告与 ResourceWarning)。

约定: 警告治理只能在调用点用 catch_warnings + 具体类别。
"""

import importlib
import sys
import warnings

import pytest

TARGET_MODULES = [
    "backend.news_data",
    "backend.fundamentals",
    "backend.fund_flow",
    "backend.providers.akshare_provider",
]

BARE_IGNORE = ("ignore", None, Warning, None, 0)


@pytest.mark.parametrize("module", TARGET_MODULES)
def test_import_does_not_silence_warnings(module):
    for name in list(sys.modules):
        if name == module or name.startswith(module + "."):
            del sys.modules[name]
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        importlib.import_module(module)
    assert warnings.filters[0] != BARE_IGNORE, f"{module} import 后 warnings.filters[0] 是裸全局静默 {BARE_IGNORE!r}"
