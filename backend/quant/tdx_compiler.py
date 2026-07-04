"""通达信(TDX)公式编译器 — 把 TDX 选股/指标公式子集编译成可回测的买卖信号。

支持一个**实用子集**:数据引用、常用指标函数、算术/比较/逻辑运算、中间变量赋值,
以及 ENTERLONG/EXITLONG(或 BUY/SELL)信号输出。每个表达式编译成一条与 bar 对齐的
时间序列(list[float], 预热段为 NaN),信号为逐 bar 布尔序列。

**防未来函数**:所有函数(MA/EMA/REF/HHV/CROSS…)只回看 ≤ i 的数据,绝不前视;
配合回测引擎「T 日信号→T+1 成交」天然防未来函数。

**失败安全**:词法/语法/求值错误都被捕获并以 `errors` 返回,绝不抛到调用方;坏公式
编译为「无信号」,回测即 0 交易,不伪造成功。

合规:公式由用户自定义,本模块只做确定性计算,不预测、不荐股。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

_NAN = float("nan")

# 数据引用(大小写不敏感,含单字母简写)。
_DATA_REFS = {
    "CLOSE": "close",
    "C": "close",
    "OPEN": "open",
    "O": "open",
    "HIGH": "high",
    "H": "high",
    "LOW": "low",
    "L": "low",
    "VOL": "volume",
    "V": "volume",
    "VOLUME": "volume",
}

# 买/卖信号关键字(大小写不敏感)。
_BUY_KEYWORDS = {"ENTERLONG", "BUY", "SIG_BUY", "ENTERSHORT_COVER"}
_SELL_KEYWORDS = {"EXITLONG", "SELL", "SIG_SELL"}

# 支持的函数及其参数个数(period 类参数必须是字面量整数)。
_FUNCS = {
    "MA": 2,
    "EMA": 2,
    "SMA": 3,
    "REF": 2,
    "HHV": 2,
    "LLV": 2,
    "SUM": 2,
    "COUNT": 2,
    "MAX": 2,
    "MIN": 2,
    "ABS": 1,
    "CROSS": 2,
    "IF": 3,
    "AVEDEV": 2,
    "STD": 2,
}

_MAX_FORMULA_LEN = 8000
_MAX_STATEMENTS = 64
_MAX_PERIOD = 1000


class TdxError(Exception):
    """编译/求值期的内部异常,统一被入口捕获成 errors。"""


# ---------------------------------------------------------------------------
# 词法
# ---------------------------------------------------------------------------

_TWO_CHAR_OPS = {">=", "<=", "<>", "!=", "==", ":="}
_ONE_CHAR_OPS = set("+-*/()><=,:;")


def tokenize(src: str) -> list[tuple[str, Any]]:
    """切词。返回 (kind, value) 列表,kind ∈ num|name|op。"""
    tokens: list[tuple[str, Any]] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\r\n":
            i += 1
            continue
        # 注释:{...} 或 // 到行尾(TDX 习惯)
        if ch == "{":
            j = src.find("}", i)
            i = n if j < 0 else j + 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i
            while j < n and (src[j].isdigit() or src[j] == "."):
                j += 1
            try:
                tokens.append(("num", float(src[i:j])))
            except ValueError:
                raise TdxError(f"非法数字: {src[i:j]}")
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            tokens.append(("name", src[i:j].upper()))
            i = j
            continue
        two = src[i : i + 2]
        if two in _TWO_CHAR_OPS:
            tokens.append(("op", two))
            i += 2
            continue
        if ch in _ONE_CHAR_OPS:
            tokens.append(("op", ch))
            i += 1
            continue
        raise TdxError(f"无法识别的字符: {ch!r}")
    return tokens


# ---------------------------------------------------------------------------
# 语法(递归下降 + 优先级)
# ---------------------------------------------------------------------------

# AST 用元组表示:
#  ('num', x) ('var', NAME) ('call', FNAME, [args])
#  ('neg', a) ('bin', op, a, b) ('cmp', op, a, b)
#  ('and', a, b) ('or', a, b) ('not', a)


class _Parser:
    def __init__(self, tokens: list[tuple[str, Any]]):
        self.toks = tokens
        self.pos = 0

    def _peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else ("eof", None)

    def _next(self):
        t = self._peek()
        self.pos += 1
        return t

    def _expect_op(self, op: str):
        t = self._peek()
        if t[0] == "op" and t[1] == op:
            self.pos += 1
            return
        raise TdxError(f"缺少 '{op}'")

    def parse_expr(self):
        return self._or()

    def _or(self):
        node = self._and()
        while self._peek() == ("name", "OR") or self._peek() == ("op", "||"):
            self._next()
            node = ("or", node, self._and())
        return node

    def _and(self):
        node = self._not()
        while self._peek() == ("name", "AND") or self._peek() == ("op", "&&"):
            self._next()
            node = ("and", node, self._not())
        return node

    def _not(self):
        if self._peek() == ("name", "NOT"):
            self._next()
            return ("not", self._not())
        return self._compare()

    def _compare(self):
        node = self._add()
        t = self._peek()
        if t[0] == "op" and t[1] in (">", "<", ">=", "<=", "=", "==", "<>", "!="):
            self._next()
            op = "=" if t[1] == "==" else ("<>" if t[1] == "!=" else t[1])
            node = ("cmp", op, node, self._add())
        return node

    def _add(self):
        node = self._mul()
        while self._peek()[0] == "op" and self._peek()[1] in ("+", "-"):
            op = self._next()[1]
            node = ("bin", op, node, self._mul())
        return node

    def _mul(self):
        node = self._unary()
        while self._peek()[0] == "op" and self._peek()[1] in ("*", "/"):
            op = self._next()[1]
            node = ("bin", op, node, self._unary())
        return node

    def _unary(self):
        if self._peek() == ("op", "-"):
            self._next()
            return ("neg", self._unary())
        if self._peek() == ("op", "+"):
            self._next()
            return self._unary()
        return self._atom()

    def _atom(self):
        t = self._peek()
        if t[0] == "num":
            self._next()
            return ("num", t[1])
        if t[0] == "op" and t[1] == "(":
            self._next()
            node = self._or()
            self._expect_op(")")
            return node
        if t[0] == "name":
            self._next()
            name = t[1]
            if self._peek() == ("op", "("):
                self._next()
                args = []
                if self._peek() != ("op", ")"):
                    args.append(self._or())
                    while self._peek() == ("op", ","):
                        self._next()
                        args.append(self._or())
                self._expect_op(")")
                return ("call", name, args)
            return ("var", name)
        raise TdxError(f"非预期的符号: {t[1]!r}")


# ---------------------------------------------------------------------------
# 编译结果
# ---------------------------------------------------------------------------


@dataclass
class CompiledFormula:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    statements: list[tuple[str, str, Any]] = field(default_factory=list)  # (kind, name, ast)
    buy_names: list[str] = field(default_factory=list)
    sell_names: list[str] = field(default_factory=list)
    var_names: list[str] = field(default_factory=list)
    refs_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "var_names": self.var_names,
            "buy_signals": self.buy_names,
            "sell_signals": self.sell_names,
            "refs_used": self.refs_used,
            "statement_count": len(self.statements),
        }


def compile_formula(src: str) -> CompiledFormula:
    """把公式编译成语句列表(不执行)。失败安全:错误以 errors 返回,绝不抛出。"""
    if not src or not src.strip():
        return CompiledFormula(ok=False, errors=["公式为空。"])
    if len(src) > _MAX_FORMULA_LEN:
        return CompiledFormula(ok=False, errors=[f"公式过长(>{_MAX_FORMULA_LEN} 字符)。"])

    statements: list[tuple[str, str, Any]] = []
    buy_names: list[str] = []
    sell_names: list[str] = []
    var_names: list[str] = []
    refs_used: set[str] = set()
    errors: list[str] = []
    warnings: list[str] = []

    raw_stmts = [s for s in src.split(";") if s.strip()]
    if len(raw_stmts) > _MAX_STATEMENTS:
        return CompiledFormula(ok=False, errors=[f"语句过多(>{_MAX_STATEMENTS} 条)。"])

    for idx, raw in enumerate(raw_stmts):
        text = raw.strip()
        try:
            kind, name, expr_src = _split_statement(text)
            tokens = tokenize(expr_src)
            if not tokens:
                raise TdxError("空表达式")
            parser = _Parser(tokens)
            ast = parser.parse_expr()
            if parser.pos != len(parser.toks):
                raise TdxError("表达式有多余符号")
            _collect_refs(ast, refs_used, var_names, errors)
            if kind == "assign" or kind == "output":
                if name and name not in var_names:
                    var_names.append(name)
            if kind == "output" and name in _BUY_KEYWORDS:
                buy_names.append(name)
            elif kind == "output" and name in _SELL_KEYWORDS:
                sell_names.append(name)
            statements.append((kind, name, ast))
        except TdxError as e:
            errors.append(f"第 {idx + 1} 句「{text[:40]}」: {e}")
        except Exception as e:  # noqa: BLE001 — 失败安全:任何意外都收敛成可读错误
            errors.append(f"第 {idx + 1} 句解析失败: {e}")

    if not buy_names and not errors:
        warnings.append("未定义买入信号(ENTERLONG/BUY:),回测将不产生买入。")

    return CompiledFormula(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        statements=statements,
        buy_names=buy_names,
        sell_names=sell_names,
        var_names=var_names,
        refs_used=sorted(refs_used),
    )


def _split_statement(text: str) -> tuple[str, str, str]:
    """切出 (kind, name, expr_src)。kind ∈ assign(:=) | output(:) | expr。"""
    if ":=" in text:
        name, expr = text.split(":=", 1)
        return "assign", name.strip().upper(), expr
    # 区分输出冒号 ':' 与比较 '<=' '>=' 等已在 token 层处理;这里只看裸 ':'。
    # 形如 NAME: expr 的输出语句:冒号左侧是单一标识符。
    colon = _find_output_colon(text)
    if colon >= 0:
        name = text[:colon].strip().upper()
        expr = text[colon + 1 :]
        if name.replace("_", "").isalnum():
            return "output", name, expr
    return "expr", "", text


def _find_output_colon(text: str) -> int:
    """找到「输出冒号」位置:左边是单一标识符、且不是 := / >= / <= 的一部分。"""
    for i, ch in enumerate(text):
        if ch == ":":
            if i + 1 < len(text) and text[i + 1] == "=":
                return -1  # := 赋值,交给上层
            left = text[:i].strip()
            if left and left.replace("_", "").isalnum() and not left[0].isdigit():
                return i
            return -1
    return -1


def _collect_refs(ast: Any, refs: set[str], var_names: list[str], errors: list[str]) -> None:
    """遍历 AST 记录用到的数据引用,并校验函数名/参数。"""
    if not isinstance(ast, tuple):
        return
    tag = ast[0]
    if tag == "var":
        name = ast[1]
        if name in _DATA_REFS:
            refs.add(name)
        # 其它裸名字假定是已/将赋值的变量;求值期再校验是否已定义。
    elif tag == "call":
        fname, args = ast[1], ast[2]
        if fname not in _FUNCS:
            errors.append(f"未知函数 {fname}()")
        elif len(args) != _FUNCS[fname]:
            errors.append(f"{fname}() 需要 {_FUNCS[fname]} 个参数,得到 {len(args)}")
        for a in args:
            _collect_refs(a, refs, var_names, errors)
    elif tag in ("bin", "cmp"):
        _collect_refs(ast[2], refs, var_names, errors)
        _collect_refs(ast[3], refs, var_names, errors)
    elif tag in ("and", "or"):
        _collect_refs(ast[1], refs, var_names, errors)
        _collect_refs(ast[2], refs, var_names, errors)
    elif tag in ("neg", "not"):
        _collect_refs(ast[1], refs, var_names, errors)


# ---------------------------------------------------------------------------
# 序列求值
# ---------------------------------------------------------------------------


@dataclass
class EvalResult:
    ok: bool
    errors: list[str]
    buy: list[bool]
    sell: list[bool]
    series: dict[str, list[float]]


def _const_int(ast: Any, name: str) -> int:
    if not (isinstance(ast, tuple) and ast[0] == "num"):
        raise TdxError(f"{name} 的周期参数必须是常数")
    v = int(ast[1])
    if v < 1 or v > _MAX_PERIOD:
        raise TdxError(f"{name} 的周期 {v} 超出范围(1-{_MAX_PERIOD})")
    return v


def _ma(x: list[float], p: int) -> list[float]:
    n = len(x)
    out = [_NAN] * n
    for i in range(n):
        if i < p - 1:
            continue
        window = x[i - p + 1 : i + 1]
        if any(math.isnan(v) for v in window):
            continue
        out[i] = sum(window) / p
    return out


def _ema(x: list[float], p: int) -> list[float]:
    n = len(x)
    out = [_NAN] * n
    k = 2.0 / (p + 1)
    prev = _NAN
    for i in range(n):
        v = x[i]
        if math.isnan(v):
            out[i] = prev
            continue
        prev = v if math.isnan(prev) else (v * k + prev * (1 - k))
        out[i] = prev
    return out


def _sma(x: list[float], p: int, m: int) -> list[float]:
    n = len(x)
    out = [_NAN] * n
    prev = _NAN
    for i in range(n):
        v = x[i]
        if math.isnan(v):
            out[i] = prev
            continue
        prev = v if math.isnan(prev) else (m * v + (p - m) * prev) / p
        out[i] = prev
    return out


def _ref(x: list[float], p: int) -> list[float]:
    n = len(x)
    return [x[i - p] if i - p >= 0 else _NAN for i in range(n)]


def _rolling(x: list[float], p: int, fn) -> list[float]:
    n = len(x)
    out = [_NAN] * n
    for i in range(n):
        if i < p - 1:
            continue
        window = [v for v in x[i - p + 1 : i + 1] if not math.isnan(v)]
        if len(window) < p:
            continue
        out[i] = fn(window)
    return out


def _cross(a: list[float], b: list[float]) -> list[float]:
    n = len(a)
    out = [0.0] * n
    for i in range(1, n):
        if any(math.isnan(v) for v in (a[i], b[i], a[i - 1], b[i - 1])):
            continue
        if a[i] > b[i] and a[i - 1] <= b[i - 1]:
            out[i] = 1.0
    return out


def _elementwise(a: list[float], b: list[float], fn) -> list[float]:
    n = len(a)
    out = [_NAN] * n
    for i in range(n):
        if math.isnan(a[i]) or math.isnan(b[i]):
            continue
        out[i] = fn(a[i], b[i])
    return out


def _bool_series(x: list[float]) -> list[float]:
    return [0.0 if math.isnan(v) else (1.0 if v > 0.5 else 0.0) for v in x]


class _Evaluator:
    def __init__(self, bars: list[dict], n: int):
        self.n = n
        self.refs: dict[str, list[float]] = {}
        self.vars: dict[str, list[float]] = {}
        self._bars = bars

    def _ref_series(self, ref_name: str) -> list[float]:
        col = _DATA_REFS[ref_name]
        if ref_name not in self.refs:
            self.refs[ref_name] = [float(b.get(col)) if b.get(col) is not None else _NAN for b in self._bars]
        return self.refs[ref_name]

    def eval(self, ast: Any) -> list[float]:
        tag = ast[0]
        if tag == "num":
            return [float(ast[1])] * self.n
        if tag == "var":
            name = ast[1]
            if name in _DATA_REFS:
                return self._ref_series(name)
            if name in self.vars:
                return self.vars[name]
            raise TdxError(f"未定义的名字 {name}(需先用 := 赋值或是数据引用)")
        if tag == "neg":
            return [(-v if not math.isnan(v) else _NAN) for v in self.eval(ast[1])]
        if tag == "not":
            return [(1.0 - v) for v in _bool_series(self.eval(ast[1]))]
        if tag == "bin":
            return self._binop(ast[1], self.eval(ast[2]), self.eval(ast[3]))
        if tag == "cmp":
            return self._compare(ast[1], self.eval(ast[2]), self.eval(ast[3]))
        if tag == "and":
            a, b = _bool_series(self.eval(ast[1])), _bool_series(self.eval(ast[2]))
            return [1.0 if (a[i] > 0.5 and b[i] > 0.5) else 0.0 for i in range(self.n)]
        if tag == "or":
            a, b = _bool_series(self.eval(ast[1])), _bool_series(self.eval(ast[2]))
            return [1.0 if (a[i] > 0.5 or b[i] > 0.5) else 0.0 for i in range(self.n)]
        if tag == "call":
            return self._call(ast[1], ast[2])
        raise TdxError(f"无法求值的节点 {tag}")

    def _binop(self, op: str, a: list[float], b: list[float]) -> list[float]:
        if op == "+":
            return _elementwise(a, b, lambda x, y: x + y)
        if op == "-":
            return _elementwise(a, b, lambda x, y: x - y)
        if op == "*":
            return _elementwise(a, b, lambda x, y: x * y)
        if op == "/":
            return _elementwise(a, b, lambda x, y: x / y if y != 0 else _NAN)
        raise TdxError(f"未知运算符 {op}")

    def _compare(self, op: str, a: list[float], b: list[float]) -> list[float]:
        ops = {
            ">": lambda x, y: x > y,
            "<": lambda x, y: x < y,
            ">=": lambda x, y: x >= y,
            "<=": lambda x, y: x <= y,
            "=": lambda x, y: x == y,
            "<>": lambda x, y: x != y,
        }
        fn = ops[op]
        return [
            0.0 if (math.isnan(a[i]) or math.isnan(b[i])) else (1.0 if fn(a[i], b[i]) else 0.0) for i in range(self.n)
        ]

    def _call(self, fname: str, args: list[Any]) -> list[float]:
        if fname == "MA":
            return _ma(self.eval(args[0]), _const_int(args[1], "MA"))
        if fname == "EMA":
            return _ema(self.eval(args[0]), _const_int(args[1], "EMA"))
        if fname == "SMA":
            return _sma(
                self.eval(args[0]),
                _const_int(args[1], "SMA"),
                _const_int(args[2], "SMA"),
            )
        if fname == "REF":
            return _ref(self.eval(args[0]), _const_int(args[1], "REF"))
        if fname == "HHV":
            return _rolling(self.eval(args[0]), _const_int(args[1], "HHV"), max)
        if fname == "LLV":
            return _rolling(self.eval(args[0]), _const_int(args[1], "LLV"), min)
        if fname == "SUM":
            return _rolling(self.eval(args[0]), _const_int(args[1], "SUM"), sum)
        if fname == "STD":
            return _rolling(self.eval(args[0]), _const_int(args[1], "STD"), _stdev)
        if fname == "AVEDEV":
            return _rolling(self.eval(args[0]), _const_int(args[1], "AVEDEV"), _avedev)
        if fname == "COUNT":
            return _rolling(_bool_series(self.eval(args[0])), _const_int(args[1], "COUNT"), sum)
        if fname == "MAX":
            return _elementwise(self.eval(args[0]), self.eval(args[1]), max)
        if fname == "MIN":
            return _elementwise(self.eval(args[0]), self.eval(args[1]), min)
        if fname == "ABS":
            return [(_NAN if math.isnan(v) else abs(v)) for v in self.eval(args[0])]
        if fname == "CROSS":
            return _cross(self.eval(args[0]), self.eval(args[1]))
        if fname == "IF":
            c = _bool_series(self.eval(args[0]))
            a, b = self.eval(args[1]), self.eval(args[2])
            return [a[i] if c[i] > 0.5 else b[i] for i in range(self.n)]
        raise TdxError(f"未实现的函数 {fname}")


def _stdev(window: list[float]) -> float:
    m = sum(window) / len(window)
    return math.sqrt(sum((v - m) ** 2 for v in window) / len(window))


def _avedev(window: list[float]) -> float:
    m = sum(window) / len(window)
    return sum(abs(v - m) for v in window) / len(window)


def evaluate_formula(src: str, bars: list[dict]) -> EvalResult:
    """编译并在 bars 上求值,返回买/卖布尔序列。失败安全。"""
    compiled = compile_formula(src)
    n = len(bars)
    if not compiled.ok:
        return EvalResult(False, compiled.errors, [False] * n, [False] * n, {})
    if n == 0:
        return EvalResult(True, [], [], [], {})

    ev = _Evaluator(bars, n)
    buy_acc = [False] * n
    sell_acc = [False] * n
    errors: list[str] = []
    try:
        for kind, name, ast in compiled.statements:
            series = ev.eval(ast)
            if kind in ("assign", "output") and name:
                ev.vars[name] = series
            if kind == "output" and name in _BUY_KEYWORDS:
                bs = _bool_series(series)
                buy_acc = [buy_acc[i] or bs[i] > 0.5 for i in range(n)]
            elif kind == "output" and name in _SELL_KEYWORDS:
                ss = _bool_series(series)
                sell_acc = [sell_acc[i] or ss[i] > 0.5 for i in range(n)]
    except TdxError as e:
        errors.append(str(e))
        return EvalResult(False, errors, [False] * n, [False] * n, dict(ev.vars))
    except Exception as e:  # noqa: BLE001
        errors.append(f"求值失败: {e}")
        return EvalResult(False, errors, [False] * n, [False] * n, dict(ev.vars))

    return EvalResult(True, [], buy_acc, sell_acc, dict(ev.vars))
