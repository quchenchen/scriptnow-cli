"""静态守卫：函数里用了「下划线别名」却忘了导入自己那一份。

为什么需要这条守卫
------------------

`scriptnow_cli.py` 的惯例是在函数体里局部导入（`import json as _json`、`import
hashlib as _hashlib`……共 41 处），**而模块顶部本来就有 `import json`**，所以这些
局部导入全是冗余的别名。冗余的代价在 2026-09-19 兑现：`interpret_propose` 新增时
抄了别处的 `_json.loads(...)` 却漏了那行导入，于是这条命令**从 0.4.3 起就一次都
跑不通**（`NameError: name '_json' is not defined`）。

它躲过了当时所有门禁，因为那些门禁**都不执行函数体**：

* 配方门禁证明的是「命令与选项在命令树里解析得到」（`--help` 列得出来）；
* 预装比对证明的是「源码与 wheel 逐字节一致」；
* 两者都不在乎函数体里那个名字有没有绑定。

换句话说：**编译得过 ≠ 跑得起来**，而当时的绿全是编译级的。这条守卫把那个缺口
按「整个类」补上 —— 不针对某个命令，而是任何函数只要用了一个自己没绑定的
下划线别名就报错。它便宜（纯 AST，毫秒级）、无副作用，且**每次发布都会跑**
（PyPI 工作流在打包前跑 pytest）。

守卫本身也要能被证明在工作：下面两条对照测试喂给它「历史版本那段源码」与
「修好后的源码」，前者必须报、后者必须不报。`_scan_source` 因此接受源码文本，
而不是只认磁盘上的文件。
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "cli_anything"

#: 别名形状：`_json` / `_hashlib` / `_os`。故意只认这种「下划线 + 小写单词」，
#: 不碰 `__dunder__`，也不碰 `_private_helper()` 这类真函数名。
def _looks_like_alias(name: str) -> bool:
    return (
        name.startswith("_")
        and not name.startswith("__")
        and name[1:2].islower()
        and name[1:].replace("_", "").isalnum()
        and name[1:].islower()
    )


class _OwnScope(ast.NodeVisitor):
    """收集**属于本函数自己**的名字，不进入嵌套函数/类/推导式的作用域。"""

    def __init__(self) -> None:
        self.loads: set[str] = set()
        self.bound: set[str] = set()

    # 嵌套函数：只把它的名字当成绑定，**不进它的体**（那是它自己的作用域）
    def visit_FunctionDef(self, node: ast.AST) -> None:
        self.bound.add(node.name)  # type: ignore[attr-defined]

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.AST) -> None:
        self.bound.add(node.name)  # type: ignore[attr-defined]

    def visit_Lambda(self, node: ast.AST) -> None:
        pass

    def visit_Name(self, node: ast.Name) -> None:
        (self.loads if isinstance(node.ctx, ast.Load) else self.bound).add(node.id)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.bound.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.bound.add(alias.asname or alias.name)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.bound.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.bound.update(node.names)


def _target_names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)
            and isinstance(n.ctx, ast.Store)}


def _collect_bindings(statements: list[ast.stmt], names: set[str]) -> bool:
    """收集**这一层**能绑定的名字（会进 `try:` / `if:` 这类复合语句，但不进函数与类体）。

    「模块级别名」经常写在 `try:` 里 —— `session.py` 就是这么绑 `_fcntl` / `_msvcrt` 的
    （平台不同、导入不同）。只看 `tree.body` 的直接子节点会把它们判成「没绑定」，
    于是守卫开始报假警 —— 一个会喊狼来了的门禁比没有门禁更糟。

    返回值：这一层有没有星号导入（有就放弃体检这个文件）。
    """
    opaque = False
    for node in statements:
        if isinstance(node, ast.Import):
            names |= {a.asname or a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if any(a.name == "*" for a in node.names):
                opaque = True
            names |= {a.asname or a.name for a in node.names}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)          # 只记名字，不进它的体
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names |= _target_names(target)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.For, ast.AsyncFor)):
            names |= _target_names(node.target)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    names |= _target_names(item.optional_vars)
        elif isinstance(node, (ast.Try, ast.If, ast.While)):
            for field in ("body", "orelse", "finalbody"):
                opaque |= _collect_bindings(getattr(node, field, []), names)
            for handler in getattr(node, "handlers", []):
                if handler.name:
                    names.add(handler.name)
                opaque |= _collect_bindings(handler.body, names)
    return opaque


def _module_names(tree: ast.Module) -> tuple[set[str], bool]:
    """模块级绑定的名字；第二个返回值表示「有没有星号导入」（有就放弃体检这个文件）。"""
    names: set[str] = set()
    opaque = _collect_bindings(tree.body, names)
    return names, opaque


def _scan_source(source: str, filename: str = "<source>") -> list[str]:
    tree = ast.parse(source, filename=filename)
    module_names, opaque = _module_names(tree)
    if opaque:
        return []
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        own = _OwnScope()
        for statement in node.body:
            own.visit(statement)
        arguments = {a.arg for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs}
        if node.args.vararg:
            arguments.add(node.args.vararg.arg)
        if node.args.kwarg:
            arguments.add(node.args.kwarg.arg)
        bound = own.bound | arguments | module_names
        unbound = sorted(n for n in own.loads if _looks_like_alias(n) and n not in bound)
        for name in unbound:
            findings.append(f"{filename}:{node.lineno}  {node.name}()  用了没绑定的 {name}")
    return findings


def test_scanner_detects_the_historical_defect():
    """正对照：把 0.4.3/0.4.4 那段源码原样喂进去，必须报出 `_json`。"""
    historical = '''
import json

def interpret_propose(profile_file):
    """回填来源画像候选。"""
    raw = open(profile_file).read()
    try:
        payload = _json.loads(raw)
    except _json.JSONDecodeError as error:
        raise RuntimeError(error)
    return payload
'''
    findings = _scan_source(historical, "historical.py")
    assert len(findings) == 1, findings
    assert "interpret_propose()" in findings[0]
    assert "_json" in findings[0]


def test_scanner_accepts_both_correct_shapes():
    """负对照：局部导入（本文件惯例）与直接用模块级 `json` 都要判干净。"""
    for source in (
        "import json\n\ndef f(p):\n    import json as _json\n    return _json.loads(p)\n",
        "import json\n\ndef f(p):\n    return json.loads(p)\n",
        # 别名也能由参数、with、except、推导式绑定 —— 都不能误报
        "def f(_json):\n    return _json.loads('1')\n",
        "def f(p):\n    with open(p) as _json:\n        return _json.read()\n",
        "def f(xs):\n    return [_json for _json in xs]\n",
    ):
        assert _scan_source(source) == [], source


def test_scanner_reads_aliases_bound_inside_module_level_try_blocks():
    """真实形状（`session.py` 的跨平台锁）：别名写在模块级 `try:` 里，也必须算已绑定。

    第一版守卫只看 `tree.body` 的直接子节点，于是把这两个名字报成「没绑定」——
    假警。这条测试钉住那次修正：门禁可以漏报，不可以乱报。
    """
    source = '''
try:
    import fcntl as _fcntl
except ImportError:
    _fcntl = None

try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None


def lock(fd):
    if _fcntl is not None:
        _fcntl.flock(fd, _fcntl.LOCK_EX)
    if _msvcrt is not None:
        _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
'''
    assert _scan_source(source) == []


def test_no_cli_module_uses_an_alias_it_never_binds():
    """真扫描：整个 `cli_anything/` 里一个都不许有。"""
    findings: list[str] = []
    scanned = 0
    for path in sorted(ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        scanned += 1
        findings += _scan_source(path.read_text(encoding="utf-8"),
                                 str(path.relative_to(ROOT.parent)))
    assert scanned > 5, f"只扫到 {scanned} 个文件，扫描面不对"
    assert findings == [], "\n".join(["函数用了没绑定的下划线别名（漏了局部导入）：", *findings])
