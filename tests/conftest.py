"""Make backend importable from inside tests/.

Two import styles are used across the suite:
- ``from backend.foo import bar`` (needs the repo root on sys.path)
- ``from foo import bar``        (needs the backend/ dir on sys.path)

We insert both so collection succeeds regardless of how pytest is invoked
(``pytest`` vs ``python -m pytest``) or which subdirectory a test lives in.
"""

import os
import sys
from pathlib import Path

# 默认开放 API 鉴权，避免「源码启动自动生成 token」导致全量 TestClient 401。
# 需要测鉴权的用例自行 setenv ALPHASCOPE_LOCAL_API_TOKEN。
if "ALPHASCOPE_ALLOW_OPEN_API" not in os.environ and "ALPHASCOPE_LOCAL_API_TOKEN" not in os.environ:
    os.environ["ALPHASCOPE_ALLOW_OPEN_API"] = "1"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _REPO_ROOT / "backend"
for _p in (_REPO_ROOT, _BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
