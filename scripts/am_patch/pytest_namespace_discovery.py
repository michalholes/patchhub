from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path, PurePosixPath

from .pytest_namespace_config import (
    _matches_prefix,
    _namespace_contains,
    _namespace_stem,
    _normalize_path,
    _root_namespaces,
)


class NamespaceMatcher:
    def __init__(
        self,
        *,
        namespace: str,
        path_prefix: str,
        module_prefixes: Sequence[str],
    ) -> None:
        self.namespace = _namespace_stem(namespace)
        self.path_prefix = _normalize_path(path_prefix)
        self.module_prefixes = tuple(
            prefix.strip(".")
            for prefix in module_prefixes
            if str(prefix).strip().strip(".")
        )

    def matches_module(self, module_name: str) -> bool:
        return any(
            module_name == prefix or module_name.startswith(prefix + ".")
            for prefix in self.module_prefixes
        )

    def matches_text(self, text: str) -> bool:
        if self.path_prefix and self.path_prefix in text:
            return True
        for module in self.module_prefixes:
            markers = (
                f'"{module}',
                f"'{module}",
                f" {module}.",
                f"from {module}",
                f"import {module}",
                f"({module}",
            )
            if any(marker in text for marker in markers):
                return True
        return False


class _RefCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.refs: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.refs.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.refs.add(node.module)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id == "import_module" and node.args:
            arg0 = node.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                self.refs.add(arg0.value)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            value = node.value.strip()
            if value:
                self.refs.add(value)
        self.generic_visit(node)


class _LocalImportCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.modules: list[tuple[str | None, int, tuple[str, ...] | None]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.modules.append((alias.name, 0, None))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        imported_names: tuple[str, ...] | None
        if any(alias.name == "*" for alias in node.names):
            imported_names = None
        else:
            imported_names = tuple(alias.name for alias in node.names if alias.name)
        self.modules.append((node.module, node.level, imported_names))
        self.generic_visit(node)


class _ScriptPathCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.paths: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        for keyword in node.keywords:
            if keyword.arg != "script_path":
                continue
            candidate = _path_candidate_from_expr(keyword.value)
            if candidate:
                self.paths.add(candidate)
        self.generic_visit(node)


_REPO_PY_PATH_PREFIXES = (
    "badguys/",
    "plugins/",
    "scripts/",
    "src/",
    "tests/",
)


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _test_file_paths(repo_root: Path) -> list[str]:
    tests_root = repo_root / "tests"
    if not tests_root.exists():
        return []
    out: list[str] = []
    for path in sorted(tests_root.rglob("test_*.py")):
        if path.is_file():
            out.append(_normalize_path(str(path.relative_to(repo_root))))
    return out


def _python_paths_under_tests(repo_root: Path) -> tuple[str, ...]:
    tests_root = repo_root / "tests"
    if not tests_root.exists():
        return ()
    out: list[str] = []
    for path in sorted(tests_root.rglob("*.py")):
        if path.is_file():
            out.append(_normalize_path(str(path.relative_to(repo_root))))
    return tuple(out)


def _parse_ast(text: str) -> ast.AST | None:
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def _collect_module_references(node: ast.AST) -> set[str]:
    collector = _RefCollector()
    collector.visit(node)
    return collector.refs


def _path_candidate_from_expr(node: ast.AST) -> str | None:
    parts: list[str] = []

    def visit(expr: ast.AST) -> None:
        if (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id in {"Path", "PurePath", "PurePosixPath"}
        ):
            for arg in expr.args:
                visit(arg)
            return
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
            visit(expr.left)
            visit(expr.right)
            return
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            const_value = expr.value.strip().replace("\\", "/")
            if const_value:
                parts.extend(item for item in const_value.split("/") if item)
            return
        if isinstance(expr, ast.JoinedStr):
            for part in expr.values:
                visit(part)
            return
        if isinstance(expr, ast.FormattedValue):
            return

    visit(node)
    if not parts:
        return None
    rel_path = _normalize_path("/".join(parts))
    return rel_path if rel_path.endswith(".py") else None


def _repo_python_path(value: str) -> str | None:
    norm = _normalize_path(value.strip())
    first_segment = norm.split("/", 1)[0]
    if not norm.endswith(".py") or "/" not in norm:
        return None
    if (
        norm.startswith(("/", "../"))
        or any(ch.isspace() for ch in norm)
        or first_segment.endswith(":")
        or "://" in norm
    ):
        return None
    return norm


def _collect_repo_path_refs(node: ast.AST) -> tuple[str, ...]:
    out: list[str] = []
    for child in ast.walk(node):
        candidate = _path_candidate_from_expr(child)
        if candidate is not None:
            repo_path = _repo_python_path(candidate)
            if repo_path is not None and repo_path not in out:
                out.append(repo_path)
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            repo_path = _repo_python_path(child.value)
            if repo_path is not None and repo_path not in out:
                out.append(repo_path)
    return tuple(out)


def _resolve_local_import(
    *,
    rel_path: str,
    module_name: str | None,
    level: int,
    known_paths: set[str],
) -> list[str]:
    if rel_path not in known_paths:
        return []
    module_path = PurePosixPath(rel_path)
    current_dir = module_path.parent
    candidates: list[PurePosixPath] = []
    module_parts = [item for item in (module_name or "").split(".") if item]

    if level > 0:
        anchor = current_dir
        for _ in range(max(level - 1, 0)):
            anchor = anchor.parent
        candidates.append(anchor.joinpath(*module_parts))
    elif module_name and module_name.startswith("tests."):
        candidates.append(PurePosixPath(*module_name.split(".")))
    elif module_name:
        candidates.append(current_dir.joinpath(*module_parts))
        candidates.append(PurePosixPath("tests").joinpath(*module_parts))

    out: list[str] = []
    for base in candidates:
        options: list[str] = []
        if base.name:
            options.append(_normalize_path(str(base.with_suffix(".py"))))
            options.append(_normalize_path(str(base / "__init__.py")))
        else:
            options.append(_normalize_path(str(base.parent / "__init__.py")))
        for option in options:
            if option in known_paths and option not in out:
                out.append(option)
    return out


def _collect_local_import_specs(
    *,
    rel_path: str,
    tree: ast.AST,
    known_paths: set[str],
) -> tuple[tuple[str, tuple[str, ...] | None], ...]:
    collector = _LocalImportCollector()
    collector.visit(tree)
    out: list[tuple[str, tuple[str, ...] | None]] = []
    for module_name, level, imported_names in collector.modules:
        for target in _resolve_local_import(
            rel_path=rel_path,
            module_name=module_name,
            level=level,
            known_paths=known_paths,
        ):
            item = (target, imported_names)
            if item not in out:
                out.append(item)
    return tuple(out)


def _collect_script_targets(tree: ast.AST, known_paths: set[str]) -> tuple[str, ...]:
    collector = _ScriptPathCollector()
    collector.visit(tree)
    out: list[str] = []
    for rel_path in sorted(collector.paths):
        norm = _normalize_path(rel_path)
        if norm in known_paths and norm not in out:
            out.append(norm)
    return tuple(out)


def _fixture_defs(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    out: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute):
                if target.attr == "fixture":
                    out[node.name] = node
                    break
            elif isinstance(target, ast.Name) and target.id == "fixture":
                out[node.name] = node
                break
    return out


def _fixture_arg_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    return tuple(arg.arg for arg in node.args.args if arg.arg != "self")


def _test_requested_fixtures(tree: ast.AST) -> tuple[str, ...]:
    out: list[str] = []
    for node in getattr(tree, "body", []):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        for arg in _fixture_arg_names(node):
            if arg not in out:
                out.append(arg)
    return tuple(out)


def _conftest_candidates(rel_path: str, known_paths: set[str]) -> tuple[str, ...]:
    current = PurePosixPath(rel_path).parent
    candidates: list[str] = []
    while current.parts:
        option = _normalize_path(str(current / "conftest.py"))
        if option in known_paths:
            candidates.append(option)
        if str(current) == "tests":
            break
        current = current.parent
    return tuple(candidates)


@lru_cache(maxsize=512)
def _module_details(
    repo_root_str: str,
    rel_path: str,
    known_paths_items: tuple[str, ...],
) -> tuple[
    str,
    tuple[str, ...],
    tuple[tuple[str, tuple[str, ...] | None], ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    repo_root = Path(repo_root_str)
    known_paths = set(known_paths_items)
    text = (repo_root / rel_path).read_text(encoding="utf-8")
    tree = _parse_ast(text)
    if tree is None:
        return text, (), (), (), (), (), ()
    refs = tuple(sorted(_collect_module_references(tree)))
    local_imports = _collect_local_import_specs(
        rel_path=rel_path,
        tree=tree,
        known_paths=known_paths,
    )
    script_targets = _collect_script_targets(tree, known_paths)
    repo_paths = _collect_repo_path_refs(tree)
    fixture_names = _test_requested_fixtures(tree)
    conftests = _conftest_candidates(rel_path, known_paths)
    return (
        text,
        refs,
        local_imports,
        script_targets,
        repo_paths,
        fixture_names,
        conftests,
    )


def _local_called_names(node: ast.AST) -> tuple[str, ...]:
    out: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name) and child.func.id not in out:
            out.append(child.func.id)
    return tuple(out)


def _top_level_defs(tree: ast.AST) -> dict[str, ast.stmt]:
    out: dict[str, ast.stmt] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = node
    return out


@lru_cache(maxsize=512)
def _selected_module_details(
    repo_root_str: str,
    rel_path: str,
    known_paths_items: tuple[str, ...],
    selected_names: tuple[str, ...],
) -> tuple[
    str,
    tuple[str, ...],
    tuple[tuple[str, tuple[str, ...] | None], ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    repo_root = Path(repo_root_str)
    known_paths = set(known_paths_items)
    text = (repo_root / rel_path).read_text(encoding="utf-8")
    tree = _parse_ast(text)
    if tree is None:
        return "", (), (), (), ()

    definitions = _top_level_defs(tree)
    pending = [name for name in selected_names if name in definitions]
    seen: set[str] = set()
    nodes: list[ast.stmt] = []
    while pending:
        name = pending.pop(0)
        if name in seen:
            continue
        seen.add(name)
        node = definitions[name]
        nodes.append(node)
        for helper_name in _local_called_names(node):
            if helper_name in definitions and helper_name not in seen:
                pending.append(helper_name)

    if not nodes:
        return "", (), (), (), ()

    selected_tree = ast.Module(body=list(nodes), type_ignores=[])
    selected_text = "\n\n".join(
        segment for node in nodes if (segment := ast.get_source_segment(text, node))
    )
    refs = tuple(sorted(_collect_module_references(selected_tree)))
    local_imports = _collect_local_import_specs(
        rel_path=rel_path,
        tree=selected_tree,
        known_paths=known_paths,
    )
    script_targets = _collect_script_targets(selected_tree, known_paths)
    repo_paths = _collect_repo_path_refs(selected_tree)
    return selected_text, refs, local_imports, script_targets, repo_paths


def _find_fixture_definition(
    *,
    repo_root_str: str,
    rel_path: str,
    fixture_name: str,
    known_paths_items: tuple[str, ...],
) -> tuple[str, str] | None:
    _text, _refs, _imports, _scripts, _paths, _fixtures, conftests = _module_details(
        repo_root_str,
        rel_path,
        known_paths_items,
    )
    repo_root = Path(repo_root_str)
    for conftest_path in conftests:
        tree = _parse_ast((repo_root / conftest_path).read_text(encoding="utf-8"))
        if tree is None:
            continue
        if fixture_name in _fixture_defs(tree):
            return conftest_path, fixture_name
    return None


def _collect_fixture_support_paths(
    *,
    repo_root_str: str,
    rel_path: str,
    fixture_names: Sequence[str],
    known_paths_items: tuple[str, ...],
) -> tuple[str, ...]:
    repo_root = Path(repo_root_str)
    known_paths = set(known_paths_items)
    pending = list(fixture_names)
    seen_defs: set[tuple[str, str]] = set()
    support_paths: list[str] = []

    while pending:
        fixture_name = pending.pop(0)
        fixture_ref = _find_fixture_definition(
            repo_root_str=repo_root_str,
            rel_path=rel_path,
            fixture_name=fixture_name,
            known_paths_items=known_paths_items,
        )
        if fixture_ref is None or fixture_ref in seen_defs:
            continue
        seen_defs.add(fixture_ref)
        conftest_path, actual_name = fixture_ref
        tree = _parse_ast((repo_root / conftest_path).read_text(encoding="utf-8"))
        if tree is None:
            continue
        node = _fixture_defs(tree).get(actual_name)
        if node is None:
            continue

        for arg in _fixture_arg_names(node):
            if arg not in pending:
                pending.append(arg)

        refs = _collect_module_references(node)
        local_imports = _collect_local_import_specs(
            rel_path=conftest_path,
            tree=node,
            known_paths=known_paths,
        )
        script_targets = _collect_script_targets(node, known_paths)
        for target, _selected_names in local_imports:
            if target not in support_paths:
                support_paths.append(target)
        for target in script_targets:
            if target not in support_paths:
                support_paths.append(target)

        for ref in refs:
            for target in _resolve_local_import(
                rel_path=conftest_path,
                module_name=ref,
                level=0,
                known_paths=known_paths,
            ):
                if target not in support_paths:
                    support_paths.append(target)

    return tuple(support_paths)


def _filename_fallback_candidates(
    *,
    rel_path: str,
    matchers: Sequence[NamespaceMatcher],
) -> set[str]:
    norm = _normalize_path(rel_path)
    out: set[str] = set()
    for matcher in matchers:
        prefix = matcher.path_prefix.rstrip("/")
        if not prefix.startswith("plugins/"):
            continue
        leaf = prefix.rsplit("/", 1)[-1]
        if leaf and leaf in norm:
            out.add(matcher.namespace)
    return out


def _matcher_defs(
    *,
    roots: Mapping[str, str],
    tree: Mapping[str, str],
    namespace_modules: Mapping[str, Sequence[str]],
) -> tuple[NamespaceMatcher, ...]:
    matchers: dict[str, NamespaceMatcher] = {}
    for raw_namespace, prefix in roots.items():
        namespace = _namespace_stem(raw_namespace)
        if namespace == "*":
            continue
        matchers.setdefault(
            namespace,
            NamespaceMatcher(
                namespace=namespace,
                path_prefix=prefix,
                module_prefixes=namespace_modules.get(namespace, ()),
            ),
        )
    for namespace, prefix in tree.items():
        stem = _namespace_stem(namespace)
        matchers[stem] = NamespaceMatcher(
            namespace=namespace,
            path_prefix=prefix,
            module_prefixes=namespace_modules.get(stem, ()),
        )
    ordered = sorted(
        matchers.values(), key=lambda item: (-len(item.namespace), item.namespace)
    )
    return tuple(ordered)


def _reduce_candidates(candidates: set[str]) -> tuple[str, ...]:
    reduced: list[str] = []
    for candidate in sorted(candidates, key=lambda item: (-len(item), item)):
        if any(_namespace_contains(existing, candidate) for existing in reduced):
            continue
        reduced.append(candidate)
    return tuple(sorted(reduced))


def _is_catchall_surface(
    *,
    rel_path: str,
    roots: Mapping[str, str],
    tree: Mapping[str, str],
) -> bool:
    norm = _normalize_path(rel_path)
    if _matches_prefix(norm, "tests"):
        return False
    if any(_matches_prefix(norm, prefix) for prefix in tree.values()):
        return False
    return not any(
        _namespace_stem(namespace) != "*" and _matches_prefix(norm, prefix)
        for namespace, prefix in roots.items()
    )


def _collect_candidates(
    *,
    text: str,
    refs: Sequence[str],
    matchers: Sequence[NamespaceMatcher],
    known_roots: set[str],
) -> set[str]:
    candidates: set[str] = set()
    for matcher in matchers:
        if any(matcher.matches_module(ref) for ref in refs) or matcher.matches_text(
            text
        ):
            candidates.add(matcher.namespace)
    if candidates:
        return candidates
    for root in known_roots:
        root_prefix = root + "."
        if any(ref.startswith(root_prefix) for ref in refs):
            candidates.add(root)
    return candidates


@lru_cache(maxsize=32)
def discover_namespace_ownership(
    repo_root_str: str,
    roots_items: tuple[tuple[str, str], ...],
    tree_items: tuple[tuple[str, str], ...],
    namespace_modules_items: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    repo_root = Path(repo_root_str)
    roots = dict(roots_items)
    tree = dict(tree_items)
    namespace_modules = {key: list(values) for key, values in namespace_modules_items}
    matchers = _matcher_defs(
        roots=roots,
        tree=tree,
        namespace_modules=namespace_modules,
    )
    known_roots = set(_root_namespaces(roots))
    known_paths = _python_paths_under_tests(repo_root)

    ownership: list[tuple[str, tuple[str, ...]]] = []
    for rel_path in _test_file_paths(repo_root):
        text, refs, local_imports, script_targets, _paths, fixture_names, _conftests = (
            _module_details(
                repo_root_str,
                rel_path,
                known_paths,
            )
        )
        candidates = _collect_candidates(
            text=text,
            refs=refs,
            matchers=matchers,
            known_roots=known_roots,
        )

        pending: list[tuple[str, tuple[str, ...] | None]] = list(local_imports)
        pending.extend((target, None) for target in script_targets)
        pending.extend(
            (target, None)
            for target in _collect_fixture_support_paths(
                repo_root_str=repo_root_str,
                rel_path=rel_path,
                fixture_names=fixture_names,
                known_paths_items=known_paths,
            )
        )
        seen_full: set[str] = set()
        seen_selected: set[tuple[str, tuple[str, ...]]] = set()
        while pending:
            support_path, selected_names = pending.pop(0)
            if support_path == rel_path:
                continue

            names_key = None
            if selected_names is None:
                if support_path in seen_full:
                    continue
                seen_full.add(support_path)
            else:
                names_key = tuple(dict.fromkeys(selected_names))
                if (
                    support_path in seen_full
                    or (support_path, names_key) in seen_selected
                ):
                    continue
                seen_selected.add((support_path, names_key))

            if names_key is None:
                support_text, support_refs, imports, scripts, _paths, _fix, _conf = (
                    _module_details(
                        repo_root_str,
                        support_path,
                        known_paths,
                    )
                )
            else:
                support_text, support_refs, imports, scripts, _paths = (
                    _selected_module_details(
                        repo_root_str,
                        support_path,
                        known_paths,
                        names_key,
                    )
                )
            candidates.update(
                _collect_candidates(
                    text=support_text,
                    refs=support_refs,
                    matchers=matchers,
                    known_roots=known_roots,
                )
            )
            for target, child_names in imports:
                pending.append((target, child_names))
            for target in scripts:
                pending.append((target, None))

        if not candidates:
            candidates.update(
                _filename_fallback_candidates(rel_path=rel_path, matchers=matchers)
            )
        namespaces = _reduce_candidates(candidates) or ("*",)
        ownership.append((rel_path, namespaces))
    return tuple(ownership)


@lru_cache(maxsize=32)
def discover_catchall_path_ownership(
    repo_root_str: str,
    roots_items: tuple[tuple[str, str], ...],
    tree_items: tuple[tuple[str, str], ...],
    namespace_modules_items: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    del namespace_modules_items
    repo_root = Path(repo_root_str)
    roots = dict(roots_items)
    tree = dict(tree_items)
    known_paths = _python_paths_under_tests(repo_root)

    ownership: list[tuple[str, tuple[str, ...]]] = []
    for rel_path in _test_file_paths(repo_root):
        (
            _text,
            _refs,
            local_imports,
            script_targets,
            repo_paths,
            fixture_names,
            _conf,
        ) = _module_details(
            repo_root_str,
            rel_path,
            known_paths,
        )
        candidates = [
            path
            for path in repo_paths
            if _is_catchall_surface(rel_path=path, roots=roots, tree=tree)
        ]

        pending: list[tuple[str, tuple[str, ...] | None]] = list(local_imports)
        pending.extend((target, None) for target in script_targets)
        pending.extend(
            (target, None)
            for target in _collect_fixture_support_paths(
                repo_root_str=repo_root_str,
                rel_path=rel_path,
                fixture_names=fixture_names,
                known_paths_items=known_paths,
            )
        )
        seen_full: set[str] = set()
        seen_selected: set[tuple[str, tuple[str, ...]]] = set()
        while pending:
            support_path, selected_names = pending.pop(0)
            if support_path == rel_path:
                continue

            names_key = None
            if selected_names is None:
                if support_path in seen_full:
                    continue
                seen_full.add(support_path)
            else:
                names_key = tuple(dict.fromkeys(selected_names))
                if (
                    support_path in seen_full
                    or (support_path, names_key) in seen_selected
                ):
                    continue
                seen_selected.add((support_path, names_key))

            if names_key is None:
                _st, _rf, imports, scripts, support_paths, _fx, _cf = _module_details(
                    repo_root_str,
                    support_path,
                    known_paths,
                )
            else:
                _st, _rf, imports, scripts, support_paths = _selected_module_details(
                    repo_root_str,
                    support_path,
                    known_paths,
                    names_key,
                )
            for path in support_paths:
                if (
                    _is_catchall_surface(rel_path=path, roots=roots, tree=tree)
                    and path not in candidates
                ):
                    candidates.append(path)
            for target, child_names in imports:
                pending.append((target, child_names))
            for target in scripts:
                pending.append((target, None))

        ownership.append((rel_path, tuple(sorted(candidates))))
    return tuple(ownership)


def select_tests_for_namespaces(
    *,
    ownership: Sequence[tuple[str, Sequence[str]]],
    namespaces: Sequence[str],
    include_descendants: bool,
) -> list[str]:
    targets: list[str] = []
    wanted = [_namespace_stem(item) for item in namespaces if str(item).strip()]
    for rel_path, owned_namespaces in ownership:
        for wanted_namespace in wanted:
            if any(
                _namespace_contains(wanted_namespace, owned)
                if include_descendants
                else _namespace_stem(owned) == wanted_namespace
                for owned in owned_namespaces
            ):
                targets.append(rel_path)
                break
    return targets


def is_direct_test_path(path: str) -> bool:
    norm = _normalize_path(path)
    return (
        _matches_prefix(norm, "tests")
        and Path(norm).name.startswith("test_")
        and norm.endswith(".py")
    )
