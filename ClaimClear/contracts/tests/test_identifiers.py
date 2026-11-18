"""The contracts' look-alike table must stay identical to the settlement engine's."""

import ast
from pathlib import Path

import pytest

from claimclear_contracts import identifiers

ENGINE = Path(__file__).resolve().parents[2] / "servers" / "settlement_engine" / "engine" / "identifiers.py"


def _code(path: Path) -> str:
    """The module without its docstring, normalised through the AST."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tree.body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    return ast.dump(tree)


@pytest.mark.skipif(not ENGINE.exists(), reason="the settlement engine's source is not in this checkout")
def test_same_code_as_the_engine():
    assert _code(Path(identifiers.__file__)) == _code(ENGINE)


def test_lookalikes():
    assert identifiers.same_policy("АЅ-2025-100478", "AS-2025-100478")
    assert identifiers.has_lookalikes("АЅ-2025-100478") and not identifiers.has_lookalikes("AS-2025-100478")
    assert not identifiers.same_policy("AS-2025-100478", "AS-2025-100479")
