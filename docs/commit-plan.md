# Commit plan (awaiting approval)

Nothing has been committed or pushed. The plan was **rehearsed** in a scratch repository made from
a copy of this repository's `.git` and working tree. The exact integration script was run there,
and the full gate was run on every resulting commit, each checked out into its own worktree. After
the last commit the rehearsal's working tree was clean, which proves the final commit equals the
tested working tree.

Target branch: `feature/evidence-hardening`, based on `677ab21` (`origin/main` at the time of
writing).

| # | Message | Content | Files | Gate at this commit |
| --- | --- | --- | --- | --- |
| 1 | `feat: add deterministic invariant engine` | **Pre-existing work only**, byte-identical to the reference checkout (a second local checkout outside this repository) | 20 | locked sync, ruff, format ok; mypy n/a (not configured yet); **80 passed** |
| 2 | `feat: add experiment runner, scripted agents and CLI (Milestone 1)` | Milestone 1 and its closeout; `.mypy_cache/` added to `.gitignore` | 51 | all ok; **176 passed** |
| 3 | `fix(commerce): verify starting state against a checked-in fixture` | D3 | 4 | all ok; **180 passed** |
| 4 | `feat(commerce): add trace-aware refund ordering invariant` | D4; scenario v2 | 9 | all ok; **185 passed** |
| 5 | `fix(core): reject run outcomes that contradict invariant results` | D1 | 4 | all ok; **195 passed** |
| 6 | `feat(fault-engine): record run-global sequence and happens-before evidence` | D2, including the ordering invariant's happens-before message and evidence fields | 7 | all ok; **199 passed** |
| 7 | `build: install image from uv.lock as non-root; add CI docker job` | D7 + CI | 3 | all ok; **201 passed** |
| 8 | `docs: record Milestone 2 evidence, samples and commit plan` | ADR-006, docs, samples and their generator script, this plan | 15 | all ok; **201 passed** |

"Gate" = `uv sync --locked --extra dev` (Python 3.12), `ruff check`, `ruff format --check`, `mypy`
(where configured) and `pytest`, run on Windows.

## Changes from the first plan

- **Functional code is out of the docs commit.** The ordering invariant's reworded failure message
  and its two evidence fields (`cancel_completed_at`, `refund_started_after_completions`) moved
  into commit 6. They express D2's happens-before semantics and read D2's
  `completed_before_start`. Commit 8 now contains only documentation, samples and the script that
  regenerates the samples (tooling, not product behavior).
- **Commit 3 is formatted.** Its snapshot was taken before the formatter ran; the planned content
  is the formatted file (whitespace only).
- **Machine-specific paths removed** from the audit, the Milestone 1 closeout and this plan, in
  every commit that contains them. They now read "a second local checkout outside this
  repository" or "this checkout". Meaning is unchanged.
- **`.mypy_cache/` is ignored by the repository** from commit 2, where mypy is introduced.
  Previously only mypy's own self-generated `.gitignore` kept it out.

## Authorship and provenance

- **All commits** are authored as the repository's configured identity, matching the existing
  history.
- **Commit 1** is the pre-existing invariant-engine work. Its body states that it is committed
  unchanged.
- **Commit 2**'s body lists its few non-additive edits to commit-1 files.

## Hygiene checks on everything that would enter Git

Run over all 113 blobs introduced by the eight commits, not only the final tree:

- **Secrets:** no credential patterns (API keys, GitHub/AWS tokens, private keys).
- **Artifacts:** no virtual environments, caches, bytecode, build output, logs or bundles.
- **Machine paths and identifiers:** none in content (Windows user-profile paths, temp directories, user names, email).
- **Large files:** the largest are `uv.lock` (216 KB) and two sample JSON reports (~30 KB each).

## Execution outline (after approval)

1. **Create the commits.** On `main` at `677ab21` with nothing staged, create
   `feature/evidence-hardening`. For each commit, stage from its snapshot with
   `git --work-tree=<snapshot> add -A` and `git commit -F <message>`. Finish with a mixed
   `git reset` and require `git status` to be clean. The working tree is never modified.
2. **Push.** `git push -u origin feature/evidence-hardening`.
3. **Open a draft pull request** against `main`. The CI workflow runs on pushes to `main` and on
   pull requests, so pushing the branch alone does **not** start CI.

**Undoing step 1 before pushing** must not use `git switch main`: that would check out `677ab21`
and remove the new files from disk. Instead, move `HEAD` back without touching files:
`git symbolic-ref HEAD refs/heads/main`, then `git reset -q`, then
`git branch -D feature/evidence-hardening`.
