"""Layering guards: core is infrastructure and must not depend on features; the composition root lives outside it."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
FEATURES = ("auth", "users", "audit", "web", "cases", "schedule", "conclusions", "examinations", "reference", "admin")


def imported_modules(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_core_does_not_import_features():
    offenders = {
        f"{path.name} -> {module}"
        for path in (APP / "core").glob("*.py")
        for module in imported_modules(path)
        if module.split(".")[:2] in [["app", feature] for feature in FEATURES] or module == "app.composition"
    }
    assert offenders == set()


def test_services_do_not_depend_on_http_or_orm_session():
    offenders = {
        f"{path.relative_to(APP)} -> {module}"
        for path in APP.glob("*/service.py")
        for module in imported_modules(path)
        if module.split(".")[0] == "fastapi" or module == "sqlalchemy.ext.asyncio"
    }
    # stubs of later stages still take AsyncSession; the stage-1 services must not
    stage1 = {o for o in offenders if o.split("/")[0] in {"auth", "users", "audit"}}
    assert stage1 == set()
