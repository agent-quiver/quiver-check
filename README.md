# quiver-check

Checks a [Quiver pack](https://github.com/agent-quiver/pack-standard) against the pack standard: the same check a
pack's CI runs on every change, and Quiver runs again before it serves a release.

## What it checks

- `quiver-pack.yaml` against the pack schema; its card within 40 tokens.
- `README.md` and `CHANGELOG.md` present; `quiver-pack.lock` present when the pack has dependencies.
- Each artifact's `quiver.yaml` against the artifact schema; unique ids; each artifact in its kind's directory
  (`skills/`, `resources/`, `workflows/`, `tools/`, `agent_profiles/`), named after its id with dots as hyphens.
- A skill's `SKILL.md`: `name` equals the directory, a `description` is present.
- Dependencies between artifacts: each exists, is served, is in range, needs nothing undeclared; no cycles.
- References: every `/name` written in Markdown is a skill of this pack, every Markdown link stays inside its
  artifact.
- Budgets: a card within 40 tokens, a main document within 2,000 (a token is four characters).
- Valid frontmatter in every Markdown file.
- With a release tag: the tag is `vX.Y.Z`, equals `version`, and its CHANGELOG entry is dated.
- Optional: names the pack must not carry (`--forbid-names FILE`).
- In CI: the git history, with gitleaks.

## Use it

**Command** (Python 3.11+, [uv](https://docs.astral.sh/uv/)):

```bash
uvx --from git+https://github.com/agent-quiver/quiver-check@<commit> quiver-check path/to/pack --tag v1.0.0
```

Options: `--tag vX.Y.Z`, `--forbid-names FILE` (one name per line), `--allow-slash NAME` (a `/name` that is not
a skill, repeatable). Exit status 1 when anything fails.

**GitHub Action:**

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0   # the secret scan reads the history
- uses: agent-quiver/quiver-check@<commit>
  with:
    path: .            # the pack's root
    # tag: v1.0.0      # default: the pushed tag on refs/tags/v*
    # forbid-names: .quiver/forbidden-names.txt
    # allow-slash: healthz
    # secret-scan: "true"
```

**GitLab CI**, once this repository is public:

```yaml
include:
  - remote: https://raw.githubusercontent.com/agent-quiver/quiver-check/<commit>/gitlab/quiver-check.yml
    inputs:
      ref: <commit>
```

Pin every use to a commit until the first release tag.

## Schemas

The schemas come from [`agent-quiver/pack-standard`](https://github.com/agent-quiver/pack-standard), **pinned by
commit** until the standard is tagged `v1.0.0` (`src/quiver_check/schemas/SOURCE.yaml`). They change only through
`scripts/sync_schemas.sh <pack-standard checkout> <commit or tag>`; a test fails if a schema is edited by hand.

## Develop

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```

## Licence

Apache-2.0 (`LICENSE`).
