from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MissingEvidence:
    domain: str
    cli_name: str
    capabilities: tuple[str, ...]
    missing_commands: tuple[str, ...]


def _parse_registry_domains(registry_py: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    """Parse src/audiomason/audit/registry.py without importing project code.

    Expected shape:
      def list_domains() -> tuple[DomainSpec, ...]:
          return (
              DomainSpec(domain="X", cli_name="y", capabilities=("selftest",)),
              ...
          )
    """
    tree = ast.parse(registry_py.read_text(encoding="utf-8"), filename=str(registry_py))
    domains: list[tuple[str, str, tuple[str, ...]]] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "list_domains":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Return) and isinstance(inner.value, (ast.Tuple, ast.Call)):
                    tup = inner.value
                    if isinstance(tup, ast.Call):
                        # Unlikely but tolerate direct return DomainSpec(...)
                        calls = [tup]
                    else:
                        calls = [e for e in tup.elts if isinstance(e, ast.Call)]
                    for call in calls:
                        # match DomainSpec(...)
                        if not isinstance(call.func, ast.Name) or call.func.id != "DomainSpec":
                            continue
                        kw = {k.arg: k.value for k in call.keywords if k.arg}
                        domain_v = kw.get("domain")
                        cli_v = kw.get("cli_name")
                        cap_v = kw.get("capabilities")
                        if not (
                            isinstance(domain_v, ast.Constant) and isinstance(domain_v.value, str)
                        ):
                            continue
                        if not (isinstance(cli_v, ast.Constant) and isinstance(cli_v.value, str)):
                            continue
                        caps: list[str] = []
                        if isinstance(cap_v, (ast.Tuple, ast.List)):
                            for c in cap_v.elts:
                                if isinstance(c, ast.Constant) and isinstance(c.value, str):
                                    caps.append(c.value)
                        domains.append((domain_v.value, cli_v.value, tuple(caps)))
            break

    return domains


def check_audit_rubric_coverage(
    repo_root: Path, *, rubric_rel: str = "audit/audit_rubric.yaml"
) -> list[MissingEvidence]:
    """Return a list of missing evidence entries.

    This intentionally uses simple text scanning (no YAML dependency) and is meant to be fail-fast,
    not a full rubric validator.
    """
    registry_py = repo_root / "src" / "audiomason" / "audit" / "registry.py"
    rubric = repo_root / rubric_rel

    if not registry_py.exists():
        return [
            MissingEvidence(
                domain="(unknown)",
                cli_name="(unknown)",
                capabilities=(),
                missing_commands=(f"missing {registry_py}",),
            )
        ]

    domains = _parse_registry_domains(registry_py)

    if not rubric.exists():
        missing = []
        for d, cli, caps in domains:
            expected = _expected_commands(cli, caps)
            missing.append(
                MissingEvidence(
                    domain=d, cli_name=cli, capabilities=caps, missing_commands=tuple(expected)
                )
            )
        return missing

    text = rubric.read_text(encoding="utf-8", errors="replace")

    out: list[MissingEvidence] = []
    for d, cli, caps in domains:
        expected = _expected_commands(cli, caps)
        missing_cmds = [c for c in expected if c not in text]
        if missing_cmds:
            out.append(
                MissingEvidence(
                    domain=d, cli_name=cli, capabilities=caps, missing_commands=tuple(missing_cmds)
                )
            )
    return out


def _expected_commands(cli_name: str, caps: tuple[str, ...]) -> list[str]:
    expected: list[str] = []
    for cap in caps:
        if cap == "selftest":
            expected.append(f"python -m audiomason {cli_name} --selftest")
        elif cap == "plugins_list":
            expected.append("python -m audiomason plugins --list")
        elif cap == "plugins_validate":
            expected.append("python -m audiomason plugins --validate")
    return expected
