"""The pack check, rule by rule, on small packs built in a temporary directory."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from quiver_check import check as qc
from quiver_check.cli import main

if TYPE_CHECKING:
    from collections.abc import Callable

PACK = {
    "id": "example/engineering",
    "version": "1.0.0",
    "title": "Engineering",
    "card": "Skills for running a code base with agents.",
    "description": "A test pack.",
    "maintainers": ["example"],
    "compatibility": {"quiver": ">=1.0.0 <2.0.0"},
}
SKILL = {
    "id": "alpha",
    "kind": "skill",
    "version": "1.0.0",
    "title": "Alpha",
    "description": "A plain skill that does one thing well.",
    "owner": "example",
    "audience": ["public"],
    "lifecycle": {"status": "published"},
}


def write_manifest(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))


def add_skill(root: Path, name: str, body: str = "# Skill\n", **fields: Any) -> Path:
    d = root / "skills" / name
    write_manifest(d / "quiver.yaml", {**SKILL, "id": name, "title": name.title(), **fields})
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n{body}")
    return d


@pytest.fixture
def pack(tmp_path: Path) -> Path:
    root = tmp_path / "pack"
    add_skill(root, "alpha")
    write_manifest(root / "quiver-pack.yaml", PACK)
    (root / "README.md").write_text("# Engineering\n")
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## 1.0.0 (2026-11-12)\n\n- First release.\n")
    return root


def errors(root: Path, tag: str | None = None, **kw: Any) -> list[str]:
    return qc.check(root, tag, **kw)[1]


def with_pack(root: Path, **fields: Any) -> None:
    write_manifest(root / "quiver-pack.yaml", {**PACK, **fields})


# --- the pack ------------------------------------------------------------------


@pytest.mark.parametrize("tag", [None, "v1.0.0"])
def test_a_valid_pack_passes(pack: Path, tag: str | None) -> None:
    assert qc.check(pack, tag) == (1, [])


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda p: (p / "quiver-pack.yaml").unlink(), "quiver-pack.yaml: missing"),
        (lambda p: with_pack(p, owner="x"), "quiver-pack.yaml: (root): Additional properties"),
        (lambda p: with_pack(p, id="Engineering"), "quiver-pack.yaml: id: 'Engineering' does not match"),
        (lambda p: with_pack(p, card="x" * 161), "quiver-pack.yaml: card is 41 tokens, over the 40 budget"),
        (lambda p: (p / "README.md").unlink(), "README.md: missing"),
        (lambda p: (p / "CHANGELOG.md").unlink(), "CHANGELOG.md: missing"),
        (lambda p: (p / "CHANGELOG.md").write_text("## 0.9.0\n"), "CHANGELOG.md: no entry for 1.0.0"),
        (lambda p: with_pack(p, dependencies=[{"id": "x/base", "version": "^1"}]), "quiver-pack.lock: missing"),
    ],
)
def test_a_pack_rule_broken_fails(pack: Path, change: Callable[[Path], object], error: str) -> None:
    change(pack)
    assert any(e.startswith(error) for e in errors(pack)), errors(pack)


def test_a_lock_file_satisfies_dependencies(pack: Path) -> None:
    with_pack(pack, dependencies=[{"id": "x/base", "version": "^1.0.0"}])
    (pack / "quiver-pack.lock").write_text("{}\n")
    assert errors(pack) == []


@pytest.mark.parametrize(
    ("tag", "error"),
    [
        ("v1.0.1", "tag v1.0.1: quiver-pack.yaml version is 1.0.0"),
        ("1.0.0", "tag '1.0.0': a release tag is vX.Y.Z"),
        ("v1.0", "tag 'v1.0': a release tag is vX.Y.Z"),
    ],
)
def test_the_tag_must_be_the_manifest_version(pack: Path, tag: str, error: str) -> None:
    assert errors(pack, tag) == [error]


def test_an_unreleased_entry_passes_a_branch_but_not_a_tag(pack: Path) -> None:
    (pack / "CHANGELOG.md").write_text("# Changelog\n\n## 1.0.0 (unreleased)\n")
    assert errors(pack) == []
    assert errors(pack, "v1.0.0") == ["CHANGELOG.md: the 1.0.0 entry is still unreleased; date it before tagging"]


# --- artifacts -----------------------------------------------------------------


def test_the_artifact_schema_is_checked(pack: Path) -> None:
    write_manifest(pack / "skills" / "alpha" / "quiver.yaml", {**SKILL, "version": "one"})
    assert any("skills/alpha/quiver.yaml: version: 'one' does not match" in e for e in errors(pack))


def test_duplicate_ids_fail(pack: Path) -> None:
    d = add_skill(pack, "beta")
    write_manifest(d / "quiver.yaml", {**SKILL})  # id alpha again
    assert any("duplicate id alpha" in e for e in errors(pack))


@pytest.mark.parametrize(
    ("skill_md", "error"),
    [
        ("---\nname: beta\ndescription: x\n---\n", "skills/alpha/quiver.yaml: SKILL.md name 'beta' != 'alpha'"),
        ("---\nname: alpha\n---\n", "skills/alpha/quiver.yaml: SKILL.md has no description"),
    ],
)
def test_a_skills_frontmatter_must_match(pack: Path, skill_md: str, error: str) -> None:
    (pack / "skills" / "alpha" / "SKILL.md").write_text(skill_md)
    assert error in errors(pack)


def test_a_missing_entrypoint_fails(pack: Path) -> None:
    (pack / "skills" / "alpha" / "SKILL.md").unlink()
    assert errors(pack) == ["skills/alpha/quiver.yaml: missing SKILL.md"]


def test_an_artifact_outside_its_kind_directory_fails(pack: Path) -> None:
    (pack / "skills" / "alpha").rename(pack / "misc")
    (pack / "skills").rmdir()
    assert "misc/quiver.yaml: a skill belongs in skills/<name>/quiver.yaml" in errors(pack)


def test_any_kind_needs_its_directory_named_after_the_id(pack: Path) -> None:
    res = pack / "resources" / "style"
    write_manifest(res / "quiver.yaml", {**SKILL, "id": "standards.style", "kind": "resource", "entrypoint": "r.md"})
    (res / "r.md").write_text("# Style\n")
    assert "resources/style/quiver.yaml: directory 'style' != the id with dots as hyphens" in errors(pack)


# --- dependencies --------------------------------------------------------------


@pytest.mark.parametrize(
    ("beta", "dep", "error"),
    [
        (None, {"id": "beta", "range": "^1.0.0"}, "alpha -> beta: unknown dependency"),
        ({"version": "2.0.0"}, {"id": "beta", "range": "^1.0.0"}, "alpha -> beta: version 2.0.0 is not in range"),
        ({"lifecycle": {"status": "draft"}}, {"id": "beta", "range": "^1.0.0"}, "alpha -> beta: dependency is draft"),
        ({"requires": ["mail"]}, {"id": "beta", "range": "^1.0.0"}, "alpha -> beta: dependency requires mail"),
        ({}, {"id": "beta", "range": "about one"}, "alpha -> beta: range 'about one' is not understood"),
    ],
)
def test_each_broken_edge_names_its_rule(pack: Path, beta: dict[str, Any] | None, dep: Any, error: str) -> None:
    write_manifest(pack / "skills" / "alpha" / "quiver.yaml", {**SKILL, "dependencies": [dep]})
    if beta is not None:
        add_skill(pack, "beta", **beta)
    assert any(e.startswith(error) for e in errors(pack)), errors(pack)


def test_audiences_are_not_compared_inside_a_pack(pack: Path) -> None:
    write_manifest(
        pack / "skills" / "alpha" / "quiver.yaml",
        {**SKILL, "audience": ["public"], "dependencies": [{"id": "beta", "range": "^1.0.0"}]},
    )
    add_skill(pack, "beta", audience=["internal"])
    assert errors(pack) == []


def test_a_cycle_fails(pack: Path) -> None:
    write_manifest(
        pack / "skills" / "alpha" / "quiver.yaml", {**SKILL, "dependencies": [{"id": "beta", "range": "^1"}]}
    )
    add_skill(pack, "beta", dependencies=[{"id": "alpha", "range": "^1.0.0"}])
    assert "dependency cycle: alpha -> beta -> alpha" in errors(pack)


@pytest.mark.parametrize(
    ("version", "spec", "ok"),
    [
        ("1.2.3", "^1.0.0", True),
        ("2.0.0", "^1.0.0", False),
        ("0.2.5", "^0.2.0", True),
        ("0.3.0", "^0.2.0", False),
        ("1.2.9", "~1.2.0", True),
        ("1.3.0", "~1.2.0", False),
        ("1.5.0", ">=1.0.0 <2.0.0", True),
        ("1.0.0", "1.0.0", True),
        ("1.10.0", ">1.9.0", True),
    ],
)
def test_satisfies(version: str, spec: str, ok: bool) -> None:
    assert qc.satisfies(version, spec) is ok


# --- references, budgets, names, frontmatter ------------------------------------


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ("Then run `/gamma` on it.\n", "skills/alpha/SKILL.md: /gamma is not a skill in this pack"),
        ("See [x](MISSING.md).\n", "skills/alpha/SKILL.md: link MISSING.md does not resolve"),
        ("See [x](../beta/SKILL.md).\n", "skills/alpha/SKILL.md: link ../beta/SKILL.md does not resolve"),
    ],
)
def test_references_must_resolve(pack: Path, body: str, error: str) -> None:
    add_skill(pack, "beta")
    add_skill(pack, "alpha", body)
    assert any(e.startswith(error) for e in errors(pack)), errors(pack)


def test_a_slash_name_of_this_pack_or_allowed_passes(pack: Path) -> None:
    add_skill(pack, "beta")
    add_skill(pack, "alpha", "Run `/beta`, then check `/healthz`.\n")
    assert errors(pack) == ["skills/alpha/SKILL.md: /healthz is not a skill in this pack"]
    assert errors(pack, allow_slash=["healthz"]) == []


def test_a_main_document_over_budget_fails(pack: Path) -> None:
    add_skill(pack, "alpha", "x" * 8_001)
    assert errors(pack) == [
        "skills/alpha/SKILL.md: main document is 2001 tokens, over the 2000 budget; "
        "keep every step and MUST, move explanation to a supporting file"
    ]


def test_a_skills_frontmatter_does_not_count_toward_its_budget(pack: Path) -> None:
    add_skill(pack, "alpha", "x" * 8_000)
    assert errors(pack) == []


def test_a_card_over_budget_fails(pack: Path) -> None:
    write_manifest(pack / "skills" / "alpha" / "quiver.yaml", {**SKILL, "card": "x" * 161})
    assert any("card is 41 tokens, over the 40 budget" in e for e in errors(pack))


def test_forbidden_names_are_found_in_files_and_served_fields(pack: Path) -> None:
    add_skill(pack, "alpha", "Built for Acme Corp.\n", description="A skill the Acme team uses daily.")
    assert errors(pack, forbidden_names=["Acme"]) == [
        "skills/alpha/quiver.yaml description: carries the forbidden name 'Acme' ('Acme')",
        "skills/alpha/SKILL.md: carries the forbidden name 'Acme' ('Acme')",
    ]
    assert errors(pack, forbidden_names=["Acme Corp"])[0].endswith("('Acme Corp')")
    assert errors(pack, forbidden_names=["acm"]) == []  # whole words only


def test_hidden_files_are_not_checked_for_names(pack: Path) -> None:
    (pack / "skills" / "alpha" / ".notes").write_text("Acme")
    assert errors(pack, forbidden_names=["Acme"]) == []


def test_bad_frontmatter_anywhere_fails(pack: Path) -> None:
    (pack / "README.md").write_text("---\nkey: [unclosed\n---\n# x\n")
    assert any(e.startswith("README.md: bad frontmatter") for e in errors(pack))


# --- the schemas and the command -----------------------------------------------


def test_the_schemas_are_the_synced_ones() -> None:
    folder = Path(qc.__file__).parent / "schemas"
    source = yaml.safe_load((folder / "SOURCE.yaml").read_text())
    for name, digest in source["sha256"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, f"{name} was edited by hand"


def test_the_command_reports_and_exits(pack: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(pack), "--tag", "v1.0.0"]) == 0
    assert capsys.readouterr().out == "1 artifact(s), 0 error(s)\n"
    names = tmp_path / "names.txt"
    names.write_text("# names the pack must not carry\n\nAcme\n")
    add_skill(pack, "alpha", "Built for Acme.\n")
    assert main([str(pack), "--forbid-names", str(names)]) == 1
    assert capsys.readouterr().out == (
        "skills/alpha/SKILL.md: carries the forbidden name 'Acme' ('Acme')\n1 artifact(s), 1 error(s)\n"
    )


def test_the_command_refuses_a_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path / "nope")])
    assert exc.value.code == 2
