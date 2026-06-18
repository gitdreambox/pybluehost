"""SnifferSpec lives in pybluehost.sniffer, not pybluehost.cli.

Also includes a layering-guard test that fails if any pybluehost.sniffer.*
module's source code imports pybluehost.cli.*."""
import ast
import importlib
import pathlib


def test_sniffer_spec_is_importable_from_sniffer_package():
    from pybluehost.sniffer import SnifferSpec
    assert SnifferSpec is not None


def test_sniffer_spec_module_lives_under_sniffer():
    from pybluehost.sniffer.spec import SnifferSpec
    assert SnifferSpec.__module__ == "pybluehost.sniffer.spec"


def test_no_sniffer_module_imports_from_cli():
    """Static-AST scan of pybluehost/sniffer/*.py for `from pybluehost.cli`
    or `import pybluehost.cli`. Catches reverse-layer dependencies even
    if the offending module isn't currently loaded."""
    import pybluehost.sniffer
    pkg_root = pathlib.Path(pybluehost.sniffer.__file__).parent

    offenders = []
    for py in pkg_root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        source = py.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("pybluehost.cli"):
                    offenders.append(f"{py}:{node.lineno}: from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("pybluehost.cli"):
                        offenders.append(f"{py}:{node.lineno}: import {alias.name}")

    assert not offenders, "Reverse-layer imports found:\n" + "\n".join(offenders)
