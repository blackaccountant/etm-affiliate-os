# Engineering protocol

Each phase proceeds: reconnaissance, exact candidate manifest, implementation, qualification, closure audit, explicit human/ChatGPT freeze authorization, stage/commit/push, then independent freeze verification. Frozen phases are never modified without explicit authorization.

Before qualification, classify failures before editing. Do not treat a started command as passed: retain actual exit codes, pytest collection/outcome counts, and evidence. The runner uses `-p no:cacheprovider`, a unique Windows-safe `--basetemp`, `git diff --check`, exact tracked/untracked and staged boundaries, `py_compile`, Alembic sole-head and duplicate-revision checks. It never stages, commits, pushes, migrates, or provisions databases.

PostgreSQL suites require guarded local URL/role metadata, a dedicated database and, when specified, a freshness attestation. Missing configuration is a qualification-environment condition, not a production defect. Never put URLs, usernames, passwords, or attestation values in reports or evidence. Tests must preserve caller-owned snapshot/read-only conventions; historical-migration tests must use their stated historical revision rules.

Evidence is ignored JSON bound to the spec, runner, candidate hashes, base/HEAD, Git state, static checks, Alembic, and each suite. Requalify if hashes, candidate manifest, branch/base, relevant environment, required regression selection, or evidence completeness changes, or any qualification failed. Closure validates evidence integrity, semantic boundary, exact manifest, no post-qualification drift, and unresolved defects. Only then may a human explicitly authorize freeze; after commit/push, independently verify commit, remote parity, clean tree, staged boundary, and frozen-file protection.
