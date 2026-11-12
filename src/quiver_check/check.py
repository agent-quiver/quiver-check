"""The pack check: what the Quiver pack standard requires of a pack repository.

Every rule returns messages of the form ``<path>: <what is wrong>``, paths relative to the pack root.
An empty list means the pack passes. Nothing here writes, fetches or executes pack content.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from importlib import resources
from typing import TYPE_CHECKING, Any

import yaml
from jsonschema import Draft202012Validator

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

# Context-economy budgets, in tokens estimated as four characters each: stable and dependency-free.
CHARS_PER_TOKEN = 4
CARD_BUDGET = 40
MAIN_BUDGET = 2_000

KIND_DIRS = {
    "skill": "skills",
    "resource": "resources",
    "workflow": "workflows",
    "tool": "tools",
    "agent_profile": "agent_profiles",
}
SERVED_STATUSES = frozenset({"published", "deprecated"})
UNSERVED_DIRS = frozenset({"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
RELEASE_TAG = re.compile(r"^v(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$")
FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)
# A slash-name in Markdown (`/name`, a heading `# /name`): it must be a skill of this pack.
SLASH_NAME = re.compile(r"(?:(?:^|[\s(])`|^(?:#+[ \t]+)?)/([a-z][a-z0-9-]*)(?=[`\s]|$)", re.MULTILINE)
MD_LINK = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
COMPARATOR = re.compile(r"^(\^|~|>=|<=|>|<|=)?(\d+\.\d+\.\d+)$")
# Manifest fields an agent is shown; checked for forbidden names like the files themselves.
SERVED_MANIFEST_FIELDS = ("id", "title", "description", "card", "tags", "requires", "dependencies")


def tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def served_body(name: str, text: str) -> str:
    """What an agent receives for a file: a SKILL.md without its frontmatter, any other file whole."""
    if name == "SKILL.md" and (m := FRONTMATTER.match(text)):
        return text[m.end() :]
    return text


def schema(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(resources.files("quiver_check").joinpath("schemas", name).read_text())
    return data


def is_hidden(rel: Path) -> bool:
    """Not part of what an agent is served: dotfiles and anything under a dot or cache directory."""
    return rel.name.startswith(".") or any(p in UNSERVED_DIRS or p.startswith(".") for p in rel.parts[:-1])


def frontmatter(text: str) -> dict[str, Any]:
    m = FRONTMATTER.match(text)
    loaded = yaml.safe_load(m.group(1)) if m else None
    return loaded if isinstance(loaded, dict) else {}


def semver(version: str) -> tuple[int, int, int]:
    core = version.split("-", 1)[0].split("+", 1)[0]
    major, minor, patch = (int(p) for p in core.split("."))
    return major, minor, patch


def satisfies(version: str, spec: str) -> bool:
    """Whether ``version`` is in ``spec``: space-separated ``^ ~ >= <= > < =`` terms or an exact version.

    Raises ValueError for a range it does not understand."""
    have = semver(version)
    terms = spec.split()
    if not terms:
        raise ValueError(f"range {spec!r} is not understood")
    for term in terms:
        m = COMPARATOR.match(term)
        if not m:
            raise ValueError(f"range {spec!r} is not understood")
        op, want = m.group(1) or "=", semver(m.group(2))
        if op == "^":
            major, minor, patch = want
            upper = (major + 1, 0, 0) if major else (0, minor + 1, 0) if minor else (0, 0, patch + 1)
            ok = want <= have < upper
        elif op == "~":
            ok = want <= have < (want[0], want[1] + 1, 0)
        else:
            ok = {"=": have == want, ">=": have >= want, "<=": have <= want, ">": have > want, "<": have < want}[op]
        if not ok:
            return False
    return True


def cycles(graph: Mapping[str, list[str]]) -> list[list[str]]:
    """One closed path per cycle found by depth-first search."""
    found: list[list[str]] = []
    done: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in path:
            found.append([*path[path.index(node) :], node])
            return
        if node in done:
            return
        for nxt in graph.get(node, []):
            visit(nxt, [*path, node])
        done.add(node)

    for node in sorted(graph):
        visit(node, [])
    return found


def name_pattern(name: str) -> re.Pattern[str]:
    """``name`` as a whole word in any case; spaces inside it match any whitespace."""
    words = r"\s+".join(re.escape(w) for w in name.split())
    return re.compile(rf"(?<![A-Za-z0-9_]){words}(?![A-Za-z0-9_])", re.IGNORECASE)


def strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def read_names(path: Path) -> list[str]:
    """A forbidden-names file: one name per line; blank lines and lines starting with # are ignored."""
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


@dataclass
class Pack:
    """A pack repository on disk and the manifests of its artifacts."""

    root: Path
    manifests: dict[Path, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> Pack:
        pack = cls(root)
        for path in sorted(root.rglob("quiver.yaml")):
            if is_hidden(path.relative_to(root)):
                continue
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            pack.manifests[path] = loaded if isinstance(loaded, dict) else {}
        return pack

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def files(self, artifact: Path) -> list[Path]:
        """Every file an agent may be served from one artifact: all but quiver.yaml and hidden files."""
        return [
            f
            for f in sorted(artifact.rglob("*"))
            if f.is_file() and f.name != "quiver.yaml" and not is_hidden(f.relative_to(artifact))
        ]


def manifest_errors(pack: Pack) -> list[str]:
    """Each quiver.yaml against the manifest schema, unique ids, and a skill's SKILL.md."""
    validator = Draft202012Validator(schema("manifest.schema.json"))
    errors: list[str] = []
    ids: dict[str, str] = {}
    for path, data in pack.manifests.items():
        rel = pack.rel(path)
        for err in validator.iter_errors(data):
            errors.append(f"{rel}: {'/'.join(map(str, err.absolute_path)) or '(root)'}: {err.message}")
        aid = str(data.get("id"))
        if aid in ids:
            errors.append(f"{rel}: duplicate id {aid} (also in {ids[aid]})")
        ids[aid] = rel
        if data.get("kind") != "skill":
            continue
        entry = path.parent / str(data.get("entrypoint", "SKILL.md"))
        if not entry.is_file():
            errors.append(f"{rel}: missing {entry.name}")
            continue
        fm = frontmatter(entry.read_text(encoding="utf-8"))
        want = aid.replace(".", "-")
        if fm.get("name") != want:
            errors.append(f"{rel}: SKILL.md name {fm.get('name')!r} != {want!r}")
        if not fm.get("description"):
            errors.append(f"{rel}: SKILL.md has no description")
    return errors


def layout_errors(pack: Pack) -> list[str]:
    """Each artifact in its kind's directory, named after its id with dots as hyphens."""
    errors: list[str] = []
    for path, data in pack.manifests.items():
        rel = path.relative_to(pack.root)
        kind = data.get("kind")
        home = KIND_DIRS.get(str(kind))
        if home is None:
            continue  # the schema reports an unknown kind
        if len(rel.parts) != 3 or rel.parts[0] != home:
            errors.append(f"{rel.as_posix()}: a {kind} belongs in {home}/<name>/quiver.yaml")
        elif rel.parts[1] != str(data.get("id")).replace(".", "-"):
            errors.append(f"{rel.as_posix()}: directory {rel.parts[1]!r} != the id with dots as hyphens")
    return errors


def dependency_errors(pack: Pack) -> list[str]:
    """Each edge A -> B: B exists in the pack and is served, its version is in A's range, it needs nothing A
    does not declare, and the graph has no cycle. Audiences are not compared: inside a pack the repository
    decides who reads (standard §1, §7)."""
    by_id = {str(d.get("id")): d for d in pack.manifests.values()}

    def listed(data: Mapping[str, Any], key: str) -> list[Any]:
        value = data.get(key)
        return list(value) if isinstance(value, list) else []

    def status(data: Mapping[str, Any]) -> object:
        lifecycle = data.get("lifecycle")
        return lifecycle.get("status") if isinstance(lifecycle, dict) else None

    errors: list[str] = []
    graph: dict[str, list[str]] = {}
    for aid, data in sorted(by_id.items()):
        for dep in listed(data, "dependencies"):
            if not isinstance(dep, dict):
                continue  # the schema reports it
            bid, spec = str(dep.get("id")), str(dep.get("range"))
            edge = f"{aid} -> {bid}"
            target = by_id.get(bid)
            if target is None:
                errors.append(f"{edge}: unknown dependency")
                continue
            graph.setdefault(aid, []).append(bid)
            if status(data) not in SERVED_STATUSES:
                continue  # an unserved artifact is not part of the release yet
            if status(target) not in SERVED_STATUSES:
                errors.append(f"{edge}: dependency is {status(target)}, not served")
            try:
                if not satisfies(str(target.get("version")), spec):
                    errors.append(f"{edge}: version {target.get('version')} is not in range {spec!r}")
            except ValueError:
                errors.append(f"{edge}: range {spec!r} is not understood")
            extra = sorted(map(str, set(listed(target, "requires")) - set(listed(data, "requires"))))
            if extra:
                errors.append(f"{edge}: dependency requires {', '.join(extra)}, which {aid} does not")
    errors += [f"dependency cycle: {' -> '.join(cycle)}" for cycle in cycles(graph)]
    return errors


def reference_errors(pack: Pack, allow_slash: Iterable[str] = ()) -> list[str]:
    """Slash-names that are not skills of this pack, and Markdown links that leave their artifact."""
    skills = {p.parent.name for p, d in pack.manifests.items() if d.get("kind") == "skill"}
    allowed = skills | set(allow_slash)
    errors: list[str] = []
    for path in pack.manifests:
        artifact = path.parent
        for md in sorted(artifact.rglob("*.md")):
            if is_hidden(md.relative_to(artifact)):
                continue
            rel, text = pack.rel(md), md.read_text(encoding="utf-8")
            for name in sorted(set(SLASH_NAME.findall(text)) - allowed):
                errors.append(f"{rel}: /{name} is not a skill in this pack")
            for link in sorted(set(MD_LINK.findall(text))):
                target = (md.parent / link).resolve()
                if artifact.resolve() not in target.parents or not target.is_file():
                    errors.append(f"{rel}: link {link} does not resolve to a file in this artifact")
    return errors


def budget_errors(pack: Pack) -> list[str]:
    """Cards and main documents over their budgets, measured as an agent receives them."""
    errors: list[str] = []
    for path, data in pack.manifests.items():
        card = data.get("card")
        if isinstance(card, str) and tokens(card) > CARD_BUDGET:
            errors.append(f"{pack.rel(path)}: card is {tokens(card)} tokens, over the {CARD_BUDGET} budget")
        entry = str(data.get("entrypoint") or ("SKILL.md" if data.get("kind") == "skill" else ""))
        main = path.parent / entry
        if not entry or not main.is_file():
            continue  # a missing entrypoint is reported by manifest_errors
        size = tokens(served_body(entry, main.read_text(encoding="utf-8")))
        if size > MAIN_BUDGET:
            errors.append(
                f"{pack.rel(main)}: main document is {size} tokens, over the {MAIN_BUDGET} budget; "
                "keep every step and MUST, move explanation to a supporting file"
            )
    return errors


def frontmatter_errors(pack: Pack) -> list[str]:
    errors: list[str] = []
    for md in sorted(pack.root.rglob("*.md")):
        if is_hidden(md.relative_to(pack.root)):
            continue
        try:
            frontmatter(md.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            errors.append(f"{pack.rel(md)}: bad frontmatter: {str(e).splitlines()[0]}")
    return errors


def forbidden_name_errors(pack: Pack, names: Iterable[str]) -> list[str]:
    """Names the pack must not carry, in any served file or served manifest field."""
    patterns = {name: name_pattern(name) for name in names}
    if not patterns:
        return []
    errors: list[str] = []
    for path, data in pack.manifests.items():
        texts = [(f"{pack.rel(path)} {f}", " ".join(strings(data.get(f)))) for f in SERVED_MANIFEST_FIELDS]
        texts += [(pack.rel(f), f.read_text(encoding="utf-8", errors="replace")) for f in pack.files(path.parent)]
        for where, text in texts:
            for name, pattern in patterns.items():
                if hit := pattern.search(text):
                    errors.append(f"{where}: carries the forbidden name {name!r} ({hit.group(0)!r})")
    return errors


def pack_errors(pack: Pack, tag: str | None) -> list[str]:
    """The pack manifest, the required files, the lock file, and with a release tag: version and changelog."""
    path = pack.root / "quiver-pack.yaml"
    if not path.is_file():
        return ["quiver-pack.yaml: missing; a pack needs its manifest at the repository root"]
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    data: dict[str, Any] = loaded if isinstance(loaded, dict) else {}
    errors = [
        f"quiver-pack.yaml: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
        for e in Draft202012Validator(schema("pack.schema.json")).iter_errors(data)
    ]
    card = data.get("card")
    if isinstance(card, str) and tokens(card) > CARD_BUDGET:
        errors.append(f"quiver-pack.yaml: card is {tokens(card)} tokens, over the {CARD_BUDGET} budget")
    errors += [f"{name}: missing" for name in ("README.md", "CHANGELOG.md") if not (pack.root / name).is_file()]
    if data.get("dependencies") and not (pack.root / "quiver-pack.lock").is_file():
        errors.append("quiver-pack.lock: missing; a pack with dependencies pins them there")
    version = str(data.get("version"))
    if tag is not None:
        m = RELEASE_TAG.match(tag)
        if not m:
            errors.append(f"tag {tag!r}: a release tag is vX.Y.Z")
        elif m.group(1) != version:
            errors.append(f"tag {tag}: quiver-pack.yaml version is {version}")
    changelog = pack.root / "CHANGELOG.md"
    if changelog.is_file():
        heading = rf"^##\s+\[?v?{re.escape(version)}\]?(.*)$"
        entry = re.search(heading, changelog.read_text(encoding="utf-8"), re.MULTILINE)
        if entry is None:
            errors.append(f"CHANGELOG.md: no entry for {version}")
        elif tag is not None and "unreleased" in entry.group(1).lower():
            errors.append(f"CHANGELOG.md: the {version} entry is still unreleased; date it before tagging")
    return errors


def check(
    root: Path,
    tag: str | None = None,
    forbidden_names: Iterable[str] = (),
    allow_slash: Iterable[str] = (),
) -> tuple[int, list[str]]:
    """Every rule on the pack at ``root``: the number of artifacts and the messages, pack rules first."""
    pack = Pack.load(root)
    errors = pack_errors(pack, tag)
    errors += manifest_errors(pack)
    errors += layout_errors(pack)
    errors += dependency_errors(pack)
    errors += reference_errors(pack, allow_slash)
    errors += budget_errors(pack)
    errors += forbidden_name_errors(pack, forbidden_names)
    errors += frontmatter_errors(pack)
    return len(pack.manifests), errors
