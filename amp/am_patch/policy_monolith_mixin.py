from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PolicyMonolithMixin:
    gates_skip_monolith: bool = False
    gate_monolith_enabled: bool = True
    gate_monolith_mode: str = "strict"  # strict|warn_only|report_only
    gate_monolith_scan_scope: str = "patch"  # patch|workspace
    gate_monolith_extensions: list[str] = field(default_factory=lambda: [".py", ".js"])
    gate_monolith_compute_fanin: bool = True
    gate_monolith_on_parse_error: str = "fail"  # fail|warn
    gate_monolith_areas_prefixes: list[str] = field(default_factory=list)
    gate_monolith_areas_names: list[str] = field(default_factory=list)
    gate_monolith_areas_dynamic: list[str] = field(default_factory=list)

    gate_monolith_large_loc: int = 900
    gate_monolith_huge_loc: int = 1300

    gate_monolith_large_allow_loc_increase: int = 20
    gate_monolith_huge_allow_loc_increase: int = 0
    gate_monolith_large_allow_exports_delta: int = 2
    gate_monolith_huge_allow_exports_delta: int = 0
    gate_monolith_large_allow_imports_delta: int = 1
    gate_monolith_huge_allow_imports_delta: int = 0

    gate_monolith_new_file_max_loc: int = 400
    gate_monolith_new_file_max_exports: int = 25
    gate_monolith_new_file_max_imports: int = 15

    gate_monolith_hub_fanin_delta: int = 5
    gate_monolith_hub_fanout_delta: int = 5
    gate_monolith_hub_exports_delta_min: int = 3
    gate_monolith_hub_loc_delta_min: int = 100

    gate_monolith_crossarea_min_distinct_areas: int = 3

    gate_monolith_catchall_basenames: list[str] = field(
        default_factory=lambda: ["utils.py", "common.py", "helpers.py", "misc.py"]
    )
    gate_monolith_catchall_dirs: list[str] = field(
        default_factory=lambda: ["utils", "common", "helpers", "misc"]
    )
    gate_monolith_catchall_allowlist: list[str] = field(default_factory=list)
