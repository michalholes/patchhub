from pathlib import Path

import pytest
from badguys.bdg_loader import load_bdg_test


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runner_verbosity", '"debug"'),
        ("args", '["123", "msg"]'),
    ],
)
def test_loader_rejects_runner_recipe_keys(tmp_path: Path, field: str, value: str) -> None:
    path = tmp_path / "test_guard.bdg"
    path.write_text(
        (
            "\n".join(
                [
                    "[meta]",
                    "makes_commit = false",
                    "is_guard = false",
                    "",
                    "[[step]]",
                    'op = "RUN_RUNNER"',
                    f"{field} = {value}",
                ]
            )
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="runner-start recipe stays"):
        load_bdg_test(path)
