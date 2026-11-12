# Changelog

## 0.1.0 (unreleased)

- The pack check, extracted from Quiver's `quiver.py check --pack`: the pack manifest, required files, layout,
  artifact manifests, skill frontmatter, dependencies, references, budgets, frontmatter and the release tag.
- Left out, because they are one organisation's: the list of names a shared surface must not carry (now the
  optional `--forbid-names FILE`), its exceptions for `/names`, and the rule against naming a project's copy under
  `.agents/`. Audiences are not compared between dependencies: inside a pack the repository decides who reads.
- A GitHub Action (with a gitleaks scan of the history) and a GitLab CI template for `include: remote`.
- Schemas from `agent-quiver/pack-standard` at commit `4608c70`, pinned by commit until the standard's `v1.0.0`.
