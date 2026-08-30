
from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]


def _module_exports(path: Path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    exports = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    exports.add(target.id)
    return exports


def test_view_core_import_contracts():
    core_exports = {}
    for file in (ROOT / "core").glob("*.py"):
        core_exports[f"core.{file.stem}"] = _module_exports(file)

    missing = []

    for folder in ["views", "scripts"]:
        for file in (ROOT / folder).glob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module not in core_exports:
                    continue
                for imported in node.names:
                    if imported.name == "*":
                        continue
                    if imported.name not in core_exports[node.module]:
                        missing.append(
                            f"{file.relative_to(ROOT)} imports "
                            f"{imported.name} from {node.module}, but it is missing"
                        )

    assert not missing, "\n".join(missing)


def test_storage_exports_required_by_portfolio_and_operations():
    storage = _module_exports(ROOT / "core" / "storage.py")
    required = {
        "load_positions",
        "upsert_position",
        "delete_position",
        "load_theses",
        "upsert_thesis",
        "delete_thesis",
        "list_alerts",
        "add_alert",
        "delete_alert",
        "set_alert_enabled",
        "list_alert_states",
        "sync_local_state_to_cloud",
        "load_score_history",
        "load_latest_snapshot",
        "load_json_snapshot",
    }
    missing = sorted(required - storage)
    assert not missing, f"Missing core.storage exports: {missing}"
