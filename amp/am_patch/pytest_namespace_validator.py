from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .pytest_namespace_config import (
    _namespace_stem,
    _normalize_dependencies,
    _normalize_namespace_modules,
    _normalize_roots,
    _normalize_tree,
    _root_namespaces,
)


@dataclass(frozen=True)
class NamespacePolicyEvidence:
    repo_dependency_edges: dict[str, tuple[str, ...]]
    external_overrides: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class NamespaceRule:
    namespace: str
    path_prefix: str
    module_prefixes: tuple[str, ...]
    aliases: tuple[str, ...]
    path_aliases: tuple[str, ...]


@dataclass(frozen=True)
class CollectedRefs:
    module_refs: tuple[str, ...]
    path_refs: tuple[str, ...]
    bare_refs: tuple[str, ...]


class _RepoDependencyCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.module_refs: list[str] = []
        self.path_refs: list[str] = []
        self.bare_refs: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add_module_ref(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self._add_module_ref(node.module)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if not node.args:
            self.generic_visit(node)
            return
        arg0 = node.args[0]
        if not isinstance(arg0, ast.Constant) or not isinstance(arg0.value, str):
            self.generic_visit(node)
            return
        value = arg0.value.strip()
        if not value:
            self.generic_visit(node)
            return
        call_name = _call_name(node.func)
        if call_name == "import_module":
            self._add_module_ref(value)
        elif call_name == "get_plugin":
            self._add_bare_ref(value)
        else:
            self._add_path_ref(value)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            value = node.value.strip()
            if "/" in value or value.endswith((".py", ".toml")):
                self._add_path_ref(value)
        self.generic_visit(node)

    def _add_module_ref(self, module_name: str) -> None:
        text = str(module_name).strip().strip(".")
        if text and text not in self.module_refs:
            self.module_refs.append(text)

    def _add_path_ref(self, raw_value: str) -> None:
        text = _normalize_path_token(raw_value)
        if text and text not in self.path_refs:
            self.path_refs.append(text)

    def _add_bare_ref(self, raw_value: str) -> None:
        text = str(raw_value).strip()
        if text and text not in self.bare_refs:
            self.bare_refs.append(text)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _normalize_path_token(value: str) -> str:
    return str(value).strip().replace("\\", "/").lstrip("./")


def _alias_candidates(
    namespace: str,
    path_prefix: str,
    module_prefixes: Sequence[str],
) -> tuple[str, ...]:
    out: list[str] = []
    for candidate in [namespace.rsplit(".", 1)[-1], path_prefix.rstrip("/").split("/")[-1]]:
        if candidate and candidate not in out:
            out.append(candidate)
    for module_prefix in module_prefixes:
        leaf = str(module_prefix).strip().strip(".").rsplit(".", 1)[-1]
        if leaf and leaf not in out:
            out.append(leaf)
    return tuple(out)


def _path_aliases(module_prefixes: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    for module_prefix in module_prefixes:
        prefix = str(module_prefix).strip().strip(".")
        if not prefix:
            continue
        candidate = prefix.replace(".", "/") + ".py"
        if candidate not in out:
            out.append(candidate)
    return tuple(out)


def _namespace_rules(
    *,
    roots: Mapping[str, str],
    tree: Mapping[str, str],
    namespace_modules: Mapping[str, Sequence[str]],
) -> dict[str, NamespaceRule]:
    rules: dict[str, NamespaceRule] = {}
    for raw_namespace, prefix in roots.items():
        namespace = _namespace_stem(raw_namespace)
        if namespace == "*":
            continue
        prefixes = tuple(namespace_modules.get(namespace, ()))
        rules.setdefault(
            namespace,
            NamespaceRule(
                namespace=namespace,
                path_prefix=str(prefix).rstrip("/"),
                module_prefixes=prefixes,
                aliases=_alias_candidates(namespace, str(prefix), prefixes),
                path_aliases=_path_aliases(prefixes),
            ),
        )
    for namespace, prefix in tree.items():
        stem = _namespace_stem(namespace)
        prefixes = tuple(namespace_modules.get(stem, ()))
        rules[stem] = NamespaceRule(
            namespace=stem,
            path_prefix=str(prefix).rstrip("/"),
            module_prefixes=prefixes,
            aliases=_alias_candidates(stem, str(prefix), prefixes),
            path_aliases=_path_aliases(prefixes),
        )
    return rules


def _has_descendants(namespace: str, namespaces: Sequence[str]) -> bool:
    prefix = namespace + "."
    return any(candidate.startswith(prefix) for candidate in namespaces if candidate != namespace)


def _python_paths_under(repo_root: Path, path_prefix: str) -> list[Path]:
    root = repo_root / path_prefix
    if root.is_file() and root.suffix == ".py":
        return [root]
    if not root.exists() or not root.is_dir():
        return []
    return [path for path in sorted(root.rglob("*.py")) if path.is_file()]


def _collect_refs(path: Path) -> CollectedRefs:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return CollectedRefs((), (), ())
    collector = _RepoDependencyCollector()
    collector.visit(tree)
    return CollectedRefs(
        tuple(collector.module_refs),
        tuple(collector.path_refs),
        tuple(collector.bare_refs),
    )


def _leaf_namespaces(namespaces: Sequence[str]) -> set[str]:
    items = {_namespace_stem(item) for item in namespaces}
    return {item for item in items if not _has_descendants(item, tuple(items))}


def _reduce_namespaces(namespaces: set[str]) -> set[str]:
    out: set[str] = set()
    for candidate in sorted(namespaces, key=lambda item: (-len(item), item)):
        if any(existing == candidate or existing.startswith(candidate + ".") for existing in out):
            continue
        out.add(candidate)
    return out


def _matches_module_ref(module_ref: str, rule: NamespaceRule) -> bool:
    return any(
        module_ref == prefix or module_ref.startswith(prefix + ".")
        for prefix in rule.module_prefixes
    )


def _matches_path_ref(path_ref: str, rule: NamespaceRule) -> bool:
    prefix = _normalize_path_token(rule.path_prefix)
    if prefix and (path_ref == prefix or path_ref.startswith(prefix + "/")):
        return True
    return path_ref in rule.path_aliases


def _matches_bare_ref(bare_ref: str, rule: NamespaceRule) -> bool:
    return bare_ref in rule.aliases


def collect_repo_namespace_dependency_evidence(
    *,
    repo_root: Path,
    pytest_roots: Mapping[str, str],
    pytest_tree: Mapping[str, str],
    pytest_namespace_modules: Mapping[str, Sequence[str]],
    target_namespaces: Sequence[str] | None = None,
) -> dict[str, tuple[str, ...]]:
    roots = _normalize_roots(pytest_roots)
    tree = _normalize_tree(pytest_tree)
    namespace_modules = _normalize_namespace_modules(pytest_namespace_modules)
    rules = _namespace_rules(
        roots=roots,
        tree=tree,
        namespace_modules=namespace_modules,
    )
    target_set = set(target_namespaces or rules)
    out: dict[str, tuple[str, ...]] = {}
    rule_names = tuple(sorted(rules))
    for namespace, source_rule in sorted(rules.items()):
        if _has_descendants(namespace, rule_names):
            continue
        deps: set[str] = set()
        for path in _python_paths_under(repo_root, source_rule.path_prefix):
            refs = _collect_refs(path)
            matched: set[str] = set()
            for target_namespace, target_rule in rules.items():
                if target_namespace == namespace or target_namespace not in target_set:
                    continue
                if any(_matches_module_ref(ref, target_rule) for ref in refs.module_refs):
                    matched.add(target_namespace)
                    continue
                if any(_matches_path_ref(ref, target_rule) for ref in refs.path_refs):
                    matched.add(target_namespace)
                    continue
                if any(_matches_bare_ref(ref, target_rule) for ref in refs.bare_refs):
                    matched.add(target_namespace)
            deps.update(_reduce_namespaces(matched))
        out[namespace] = tuple(sorted(deps))
    return out


def validate_namespace_policy(
    *,
    repo_root: Path,
    pytest_roots: Mapping[str, str],
    pytest_tree: Mapping[str, str],
    pytest_namespace_modules: Mapping[str, Sequence[str]],
    pytest_dependencies: Mapping[str, Sequence[str]],
    pytest_external_dependencies: Mapping[str, Sequence[str]] | None = None,
) -> NamespacePolicyEvidence:
    roots = _normalize_roots(pytest_roots)
    tree = _normalize_tree(pytest_tree)
    namespace_modules = _normalize_namespace_modules(pytest_namespace_modules)
    dependencies = _normalize_dependencies(pytest_dependencies)
    external_dependencies = _normalize_dependencies(pytest_external_dependencies)
    root_namespaces = set(_root_namespaces(roots))
    endpoints = set(tree) | root_namespaces
    errors: list[str] = []

    for raw_namespace, prefix in sorted(roots.items()):
        namespace = _namespace_stem(raw_namespace)
        if namespace == "*":
            continue
        if not (repo_root / prefix).exists():
            errors.append(f"missing_root_path:{namespace}:{prefix}")
    for namespace, prefix in sorted(tree.items()):
        if not (repo_root / prefix).exists():
            errors.append(f"missing_tree_path:{namespace}:{prefix}")

    rules = _namespace_rules(
        roots=roots,
        tree=tree,
        namespace_modules=namespace_modules,
    )
    for namespace in sorted(endpoints):
        if namespace == "*":
            continue
        if (
            namespace in rules
            and _python_paths_under(repo_root, rules[namespace].path_prefix)
            and namespace not in namespace_modules
        ):
            errors.append(f"missing_namespace_module_mapping:{namespace}")

    for mapping_name, mapping in (
        ("dependency", dependencies),
        ("external_override", external_dependencies),
    ):
        for namespace, providers in sorted(mapping.items()):
            if namespace not in endpoints:
                errors.append(f"missing_{mapping_name}_endpoint:{namespace}")
            for provider in providers:
                if provider not in endpoints:
                    errors.append(f"missing_{mapping_name}_endpoint:{namespace}->{provider}")

    for namespace, providers in sorted(dependencies.items()):
        external = set(external_dependencies.get(namespace, ()))
        for provider in providers:
            if provider in external:
                errors.append(f"dependency_external_overlap:{namespace}->{provider}")

    target_namespaces = _leaf_namespaces(tuple(tree))
    for mapping in (dependencies, external_dependencies):
        for providers in mapping.values():
            target_namespaces.update(_namespace_stem(item) for item in providers)
    repo_dependency_edges = collect_repo_namespace_dependency_evidence(
        repo_root=repo_root,
        pytest_roots=roots,
        pytest_tree=tree,
        pytest_namespace_modules=namespace_modules,
        target_namespaces=tuple(sorted(target_namespaces)),
    )
    for namespace, repo_providers in sorted(repo_dependency_edges.items()):
        declared = {_namespace_stem(item) for item in dependencies.get(namespace, ())}
        for provider in repo_providers:
            if provider not in declared:
                errors.append(f"missing_repo_dependency:{namespace}->{provider}")

    for namespace, external_providers in sorted(external_dependencies.items()):
        repo_provider_set = {
            _namespace_stem(item) for item in repo_dependency_edges.get(namespace, ())
        }
        for provider in external_providers:
            if provider in repo_provider_set:
                errors.append(f"external_override_conflicts_repo:{namespace}->{provider}")

    if errors:
        raise ValueError("; ".join(errors))

    return NamespacePolicyEvidence(
        repo_dependency_edges={
            namespace: tuple(sorted(dict.fromkeys(providers)))
            for namespace, providers in sorted(repo_dependency_edges.items())
            if providers
        },
        external_overrides={
            namespace: tuple(sorted(dict.fromkeys(providers)))
            for namespace, providers in sorted(external_dependencies.items())
            if providers
        },
    )
