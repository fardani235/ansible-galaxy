# CI/CD Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two GitHub Actions workflows (`test.yml` for PRs and pushes to main, `release.yml` for `v*` tag pushes), bump the declared minimum ansible-core version to match what we test, drop stale sanity ignore files, and document the release flow in the README.

**Architecture:** Two workflow files under `.github/workflows/`. `test.yml` runs sanity (matrix across ansible-core 2.16/2.17/2.18) and unit (single ansible-core) in parallel. `release.yml` runs sequentially with pre-publish guards (tag↔galaxy.yml version match, folded changelog fragments, sanity, unit) before building the tarball and publishing to Ansible Galaxy with the `GALAXY_API_KEY` repo secret.

**Tech Stack:** GitHub Actions, `actions/checkout@v4`, `actions/setup-python@v5`, `ansible-core` (pip-installed), `ansible-test sanity --docker`, `pytest`, `ansible-galaxy collection build`, `ansible-galaxy collection publish`, antsibull-changelog (for the fragment-folded guard, which only inspects the filesystem — it doesn't run antsibull itself).

**Reference spec:** `docs/superpowers/specs/2026-05-29-cicd-pipeline-design.md`

---

## File Map

What this plan creates, modifies, and deletes:

- **Create:** `.github/workflows/test.yml` — PR + push-to-main test workflow
- **Create:** `.github/workflows/release.yml` — `v*` tag publish workflow
- **Create:** `docs/cicd-local-dryrun.md` — short doc with the exact bash snippets to dry-run the release guards locally before tagging (referenced by Task 8's verification step)
- **Modify:** `meta/runtime.yml` — bump `requires_ansible` from `">=2.14.0"` to `">=2.16.0"`
- **Modify:** `README.md` — append a `## CI/CD` section after the `## Validation` table
- **Delete:** `tests/sanity/ignore-2.14.txt`
- **Delete:** `tests/sanity/ignore-2.15.txt`

Out of scope (per spec): integration / smoke tests in CI, GitHub Release creation, OIDC trusted publishing, Dependabot, CODEOWNERS, multi-Python matrix, any changes to `galaxy.yml` (the version bump happens in the IAM PR, not here).

---

## Branch

Work happens on `spec/cicd-pipeline` (already created off `main`, current branch). The spec commit `8a17373` is already on this branch. All tasks below commit onto this branch.

---

### Task 1: Bump declared ansible-core minimum

Drops the lie in `meta/runtime.yml`: the file currently says `>=2.14.0` but we're about to start CI-testing only against 2.16+. Aligning the declared minimum with what we actually verify.

**Files:**
- Modify: `meta/runtime.yml`

- [ ] **Step 1: Read current `meta/runtime.yml`**

Run: `cat meta/runtime.yml`
Expected output starts with:
```
---
requires_ansible: ">=2.14.0"
```

- [ ] **Step 2: Edit the version**

Change the single line `requires_ansible: ">=2.14.0"` to `requires_ansible: ">=2.16.0"` using the Edit tool (or `sed -i 's/>=2\.14\.0/>=2.16.0/' meta/runtime.yml`). Leave the rest of the file untouched.

- [ ] **Step 3: Verify the change**

Run: `grep '^requires_ansible:' meta/runtime.yml`
Expected output: `requires_ansible: ">=2.16.0"`

- [ ] **Step 4: Commit**

```bash
git add meta/runtime.yml
git commit -m "ci: bump requires_ansible minimum to 2.16

Aligns declared minimum with what the new CI matrix actually tests
(2.16/2.17/2.18). 2.14 and 2.15 ignore files are deleted in a
follow-up commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Delete sanity ignore files for dropped ansible-core versions

Removes ignore files we no longer test against. Carrying them risks bit-rot (a rule that fires on 2.14 only stays "fixed" by ignore, even if the underlying issue is real on 2.16+).

**Files:**
- Delete: `tests/sanity/ignore-2.14.txt`
- Delete: `tests/sanity/ignore-2.15.txt`

- [ ] **Step 1: Confirm both files exist**

Run: `ls tests/sanity/ignore-2.1{4,5}.txt`
Expected output:
```
tests/sanity/ignore-2.14.txt
tests/sanity/ignore-2.15.txt
```

- [ ] **Step 2: Delete them**

Run: `rm tests/sanity/ignore-2.14.txt tests/sanity/ignore-2.15.txt`

- [ ] **Step 3: Verify `ignore-2.16.txt` is still present**

Run: `ls tests/sanity/`
Expected output: includes `ignore-2.16.txt` (and only that ignore file).

- [ ] **Step 4: Commit**

```bash
git add -A tests/sanity/
git commit -m "ci: drop sanity ignore files for unsupported ansible-core versions

We no longer test against 2.14 or 2.15 (see meta/runtime.yml bump);
carrying their ignore files invites bit-rot.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Write the test.yml workflow

The PR-and-push CI: sanity matrix (2.16/2.17/2.18) plus a unit job, parallel, with `cancel-in-progress` concurrency per branch.

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Ensure the workflow directory exists**

Run: `mkdir -p .github/workflows`

- [ ] **Step 2: Write the full file**

Create `.github/workflows/test.yml` with exactly this content:

```yaml
name: Test

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

concurrency:
  group: test-${{ github.ref }}
  cancel-in-progress: true

jobs:
  sanity:
    name: Sanity (ansible-core ${{ matrix.ansible-version }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        ansible-version: ['2.16', '2.17', '2.18']
    steps:
      - name: Check out collection
        uses: actions/checkout@v4
        with:
          path: ansible_collections/fardani235/byteplus

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install ansible-core ${{ matrix.ansible-version }}
        run: pip install "ansible-core==${{ matrix.ansible-version }}.*"

      - name: Run ansible-test sanity
        working-directory: ansible_collections/fardani235/byteplus
        run: ansible-test sanity --docker --python 3.11

  unit:
    name: Unit tests
    runs-on: ubuntu-latest
    steps:
      - name: Check out collection
        uses: actions/checkout@v4
        with:
          path: ansible_collections/fardani235/byteplus

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install ansible-core
        run: pip install ansible-core

      - name: Install unit test requirements
        working-directory: ansible_collections/fardani235/byteplus
        run: pip install -r tests/unit/requirements.txt

      - name: Run pytest
        working-directory: ansible_collections/fardani235/byteplus
        run: pytest tests/unit/ -v
```

- [ ] **Step 3: Validate YAML syntax locally**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))"`
Expected: no output, exit code 0.

If you get a YAMLError, re-check indentation in the step above — GHA YAML is whitespace-sensitive (2-space indents throughout, no tabs).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci: add test workflow for PRs and pushes to main

Runs ansible-test sanity across ansible-core 2.16/2.17/2.18 in parallel
plus a single unit-test job. Per-branch concurrency with
cancel-in-progress keeps CI minutes down when pushes stack up.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Write the release.yml workflow

The `v*`-tag publish workflow with pre-publish guards (tag↔galaxy.yml match, folded changelog fragments, sanity, unit) running before build and publish.

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Write the full file**

Create `.github/workflows/release.yml` with exactly this content:

```yaml
name: Release

on:
  push:
    tags: ['v*']

concurrency:
  group: release
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  release:
    name: Build and publish to Ansible Galaxy
    runs-on: ubuntu-latest
    steps:
      - name: Check out collection at tag
        uses: actions/checkout@v4
        with:
          path: ansible_collections/fardani235/byteplus

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install ansible-core
        run: pip install ansible-core

      - name: Verify tag matches galaxy.yml version
        working-directory: ansible_collections/fardani235/byteplus
        run: |
          TAG_VERSION="${GITHUB_REF_NAME#v}"
          GALAXY_VERSION="$(grep '^version:' galaxy.yml | awk '{print $2}')"
          if [ "$TAG_VERSION" != "$GALAXY_VERSION" ]; then
            echo "::error::tag $GITHUB_REF_NAME (=$TAG_VERSION) != galaxy.yml version $GALAXY_VERSION"
            exit 1
          fi
          echo "Tag and galaxy.yml both at $TAG_VERSION."

      - name: Verify changelog fragments are folded
        working-directory: ansible_collections/fardani235/byteplus
        run: |
          UNFOLDED=$(find changelogs/fragments -type f \
            \( -name '*.yml' -o -name '*.yaml' \) \
            ! -name '.placeholder' 2>/dev/null || true)
          if [ -n "$UNFOLDED" ]; then
            echo "::error::unfolded changelog fragments present; run 'antsibull-changelog release' before tagging"
            echo "$UNFOLDED"
            exit 1
          fi
          echo "No unfolded changelog fragments."

      - name: Run sanity on tagged commit
        working-directory: ansible_collections/fardani235/byteplus
        run: ansible-test sanity --docker --python 3.11

      - name: Install unit test requirements
        working-directory: ansible_collections/fardani235/byteplus
        run: pip install -r tests/unit/requirements.txt

      - name: Run unit tests on tagged commit
        working-directory: ansible_collections/fardani235/byteplus
        run: pytest tests/unit/ -v

      - name: Build collection tarball
        working-directory: ansible_collections/fardani235/byteplus
        run: ansible-galaxy collection build --output-path /tmp/dist

      - name: Publish to Ansible Galaxy
        working-directory: ansible_collections/fardani235/byteplus
        env:
          GALAXY_API_KEY: ${{ secrets.GALAXY_API_KEY }}
        run: |
          TAG_VERSION="${GITHUB_REF_NAME#v}"
          ansible-galaxy collection publish \
            "/tmp/dist/fardani235-byteplus-${TAG_VERSION}.tar.gz" \
            --api-key "$GALAXY_API_KEY"
```

Note: `GALAXY_API_KEY` is piped through an `env:` block rather than interpolated directly into the run script — keeps the secret out of the rendered command line that shows up in GHA logs.

- [ ] **Step 2: Validate YAML syntax locally**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add release workflow triggered by v* tag push

Pre-publish guards run in cheap-to-expensive order: tag<->galaxy.yml
version match, then folded-fragment check, then full sanity + unit on
the tagged commit, then build, then publish. GALAXY_API_KEY is piped
via env so it doesn't appear in the rendered command line.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Write the local-dryrun doc for the release guards

Operators need to be able to verify the release guards locally before pushing a tag. Documenting the exact bash blocks the workflow runs makes this a quick `bash docs/cicd-local-dryrun.md`-style exercise rather than archaeology.

**Files:**
- Create: `docs/cicd-local-dryrun.md`

- [ ] **Step 1: Write the doc**

Create `docs/cicd-local-dryrun.md` with this content:

````markdown
# Dry-running the release guards locally

Before you push a `vX.Y.Z` tag, run these exact checks from the repo
root. They mirror what `.github/workflows/release.yml` runs in CI; if
they pass here they should pass there.

## 1. Tag-name vs galaxy.yml version match

Set `TAG_VERSION` to the version you intend to tag (without the `v`
prefix), then:

```bash
TAG_VERSION="1.2.0"   # whatever you're about to tag
GALAXY_VERSION="$(grep '^version:' galaxy.yml | awk '{print $2}')"
if [ "$TAG_VERSION" != "$GALAXY_VERSION" ]; then
  echo "FAIL: tag $TAG_VERSION != galaxy.yml $GALAXY_VERSION"
  exit 1
fi
echo "OK: tag and galaxy.yml both at $TAG_VERSION"
```

If this fails, bump `galaxy.yml` (and add a changelog fragment for the
bump) before tagging.

## 2. Changelog fragments are folded

```bash
UNFOLDED=$(find changelogs/fragments -type f \
  \( -name '*.yml' -o -name '*.yaml' \) \
  ! -name '.placeholder' 2>/dev/null || true)
if [ -n "$UNFOLDED" ]; then
  echo "FAIL: unfolded fragments present:"
  echo "$UNFOLDED"
  exit 1
fi
echo "OK: no unfolded fragments"
```

If this fails, run `antsibull-changelog release` to fold the fragments
into `CHANGELOG.rst` (or `.md`), commit the result, then re-run.

## 3. Sanity + unit

These are the same commands CI runs:

```bash
# Sanity needs the repo at the canonical collection path.
# If you're not already at one, ansible-test will tell you.
ansible-test sanity --docker --python 3.11
pip install -r tests/unit/requirements.txt
pytest tests/unit/ -v
```

If all three sections pass, the release workflow should pass too. Tag
and push:

```bash
git tag "v${TAG_VERSION}"
git push origin "v${TAG_VERSION}"
```
````

- [ ] **Step 2: Verify the doc renders**

Run: `head -5 docs/cicd-local-dryrun.md`
Expected: starts with `# Dry-running the release guards locally`.

- [ ] **Step 3: Commit**

```bash
git add docs/cicd-local-dryrun.md
git commit -m "docs: how to dry-run the release guards locally

Mirrors the exact bash blocks release.yml runs so maintainers can
catch a misnamed tag or unfolded fragment before pushing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Add the CI/CD section to README

Operator-facing doc of what the workflows do, when they fire, and the GALAXY_API_KEY requirement.

**Files:**
- Modify: `README.md` (append after the existing `## Validation` table, at end of file)

- [ ] **Step 1: Confirm where to append**

Run: `tail -3 README.md`
Expected: the last lines of the Validation table. The new section will be appended after this.

- [ ] **Step 2: Append the section**

Append exactly this content to the end of `README.md` (note the leading blank line so the new heading is separated from the table):

```markdown

## CI/CD

This collection ships two GitHub Actions workflows under
`.github/workflows/`:

- **`test.yml`** runs on pull requests to `main` and pushes to `main`.
  It runs `ansible-test sanity` across ansible-core 2.16, 2.17, and
  2.18 in parallel plus a single `pytest tests/unit/` job. Failure on
  any matrix cell does not cancel the others (`fail-fast: false`).
- **`release.yml`** runs on `v*` tag pushes. It verifies the tag matches
  `galaxy.yml` version, verifies no unfolded `changelogs/fragments/*.yml`
  remain, re-runs sanity + unit on the tagged commit, builds the
  collection with `ansible-galaxy collection build`, then publishes to
  Ansible Galaxy. The Galaxy API token is supplied via the repo secret
  `GALAXY_API_KEY` (Settings → Secrets and variables → Actions).

**To cut a release:**

1. Bump `version:` in `galaxy.yml`.
2. Run `antsibull-changelog release` to fold pending fragments into the
   changelog. Commit.
3. (Optional, recommended) Run the local dry-run from
   `docs/cicd-local-dryrun.md` to verify the release guards pass.
4. Tag with the same version prefixed by `v` (e.g. `v1.2.0`) and push:
   `git tag v1.2.0 && git push origin v1.2.0`.

If `release.yml` fails partway through, fix the issue and retag with
the next patch version — Galaxy rejects re-uploads of the same version
number, so a failed publish never leaves a partial artifact on Galaxy.
```

You can do this with: `cat >> README.md <<'EOF'`-style heredoc, or via the Edit/Write tool. Either way, the final file must end with the snippet above.

- [ ] **Step 3: Verify the append**

Run: `tail -20 README.md`
Expected: ends with the paragraph beginning `If \`release.yml\` fails partway through, ...`.

Also run: `grep -c '^## CI/CD$' README.md`
Expected output: `1` (exactly one occurrence — if you see 2, you appended twice and need to revert one).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add CI/CD section explaining test and release workflows

Documents both workflows, when they trigger, and the release procedure
(galaxy.yml bump -> fold fragments -> tag -> push). Points operators at
docs/cicd-local-dryrun.md for the pre-tag verification.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Local dry-run the release guards

Before merging the PR, verify the two bash guard blocks from `release.yml` work correctly against the current checkout. This is the spec's "Testing the workflows" step.

**Files:** (no file changes — verification only)

- [ ] **Step 1: Verify the tag↔galaxy.yml guard catches a mismatch**

Run this with an intentionally wrong tag version to confirm the guard fails:

```bash
TAG_VERSION="9.9.9"
GALAXY_VERSION="$(grep '^version:' galaxy.yml | awk '{print $2}')"
if [ "$TAG_VERSION" != "$GALAXY_VERSION" ]; then
  echo "FAIL (expected): tag $TAG_VERSION != galaxy.yml $GALAXY_VERSION"
  exit 1
fi
```

Expected: exit code 1, message `FAIL (expected): tag 9.9.9 != galaxy.yml <current>`.

- [ ] **Step 2: Verify the tag↔galaxy.yml guard passes on a match**

Run with the version that's actually in galaxy.yml right now:

```bash
TAG_VERSION="$(grep '^version:' galaxy.yml | awk '{print $2}')"
GALAXY_VERSION="$(grep '^version:' galaxy.yml | awk '{print $2}')"
if [ "$TAG_VERSION" != "$GALAXY_VERSION" ]; then
  echo "FAIL"
  exit 1
fi
echo "OK"
```

Expected: exit code 0, message `OK`.

- [ ] **Step 3: Verify the changelog-fragment guard passes on the current clean state**

Run:

```bash
UNFOLDED=$(find changelogs/fragments -type f \
  \( -name '*.yml' -o -name '*.yaml' \) \
  ! -name '.placeholder' 2>/dev/null || true)
if [ -n "$UNFOLDED" ]; then
  echo "FAIL: unfolded:"
  echo "$UNFOLDED"
  exit 1
fi
echo "OK: no unfolded fragments"
```

Expected: exit code 0, message `OK: no unfolded fragments`.

If this step *fails*, that means there are real unfolded fragments on this branch — that's a separate issue not caused by this PR; flag it to the maintainer rather than fixing inline.

- [ ] **Step 4: Verify the changelog-fragment guard catches an unfolded fragment**

Stage a fake unfolded fragment to confirm the guard would fail at release time:

```bash
mkdir -p changelogs/fragments
echo 'minor_changes:' > changelogs/fragments/test-guard.yml
echo '  - test entry' >> changelogs/fragments/test-guard.yml
UNFOLDED=$(find changelogs/fragments -type f \
  \( -name '*.yml' -o -name '*.yaml' \) \
  ! -name '.placeholder' 2>/dev/null || true)
if [ -n "$UNFOLDED" ]; then
  echo "FAIL (expected): unfolded fragments present:"
  echo "$UNFOLDED"
  rm changelogs/fragments/test-guard.yml
  exit 1
fi
rm -f changelogs/fragments/test-guard.yml
```

Expected: exit code 1, message includes `changelogs/fragments/test-guard.yml`. The test fragment is removed at the end of the block regardless.

- [ ] **Step 5: Confirm working tree is clean**

Run: `git status`
Expected: `nothing to commit, working tree clean`.

If you see `changelogs/fragments/test-guard.yml` listed as untracked, the cleanup in Step 4 didn't run; remove it manually: `rm changelogs/fragments/test-guard.yml`.

- [ ] **Step 6: No commit needed**

This task makes no file changes — the verification is its own deliverable.

---

### Task 8: Push the branch and open the PR

The branch needs to land on origin for GHA to pick up the new workflows. The test workflow self-tests against this PR.

**Files:** (no file changes)

- [ ] **Step 1: Verify branch state**

Run: `git log --oneline main..HEAD`
Expected: 7 commits — the spec commit (`docs: spec for CI/CD pipeline`) and 6 from Tasks 1–6. (Task 7 made no commit.)

- [ ] **Step 2: Push the branch**

Run: `git push -u origin spec/cicd-pipeline`

If `gh` is not authenticated yet, the maintainer needs to run `gh auth login` first (interactive — they should type `! gh auth login` in the prompt to run it in this session, or run it in their own terminal).

- [ ] **Step 3: Open the PR**

Run:

```bash
gh pr create \
  --base main \
  --head spec/cicd-pipeline \
  --title "ci: add test + release workflows for Ansible Galaxy publishing" \
  --body "$(cat <<'EOF'
## Summary

Adds GitHub Actions CI/CD per spec
`docs/superpowers/specs/2026-05-29-cicd-pipeline-design.md`:

- **`test.yml`** — runs on PRs to main and pushes to main. Matrix sanity
  (ansible-core 2.16/2.17/2.18) + single unit job, parallel,
  `cancel-in-progress` per branch.
- **`release.yml`** — runs on `v*` tag push. Pre-publish guards
  (tag↔galaxy.yml match, folded changelog fragments, sanity, unit) run
  before build and publish to Ansible Galaxy via the `GALAXY_API_KEY`
  repo secret.

## Associated changes

- `meta/runtime.yml`: `requires_ansible` bumped from `>=2.14.0` to
  `>=2.16.0` to match the matrix.
- `tests/sanity/ignore-2.14.txt` and `ignore-2.15.txt` deleted (we no
  longer test those versions).
- `README.md`: new `## CI/CD` section documenting both workflows and
  the release procedure.
- `docs/cicd-local-dryrun.md`: pre-tag verification commands.

## Setup required before first release

1. Generate a Galaxy API token at https://galaxy.ansible.com
   (preferences → API key).
2. Add it as repo secret `GALAXY_API_KEY` (Settings → Secrets and
   variables → Actions).
3. Recommended: branch protection on `main` requiring `Test` workflow
   to pass.

## Testing

Pre-publish guard bash blocks were dry-run locally against this branch
(Task 7 of the plan); both the positive and negative cases behave as
expected. `test.yml` self-tests as soon as this PR is opened — if the
CI on this PR is green, the test workflow itself works.

`release.yml` is verified by the live first-tag (`v1.2.0`, after the
IAM PR merges). Galaxy rejects re-uploads of the same version, so a
failed publish never corrupts the registry.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Verify the PR opened and CI is running**

Run: `gh pr view --json url,statusCheckRollup`
Expected: a URL to the PR; `statusCheckRollup` shows the workflows as `IN_PROGRESS` or `PENDING` (will turn `SUCCESS` once they finish).

If the workflows do not appear at all in `statusCheckRollup`, GitHub may have rejected the workflow files for a syntax issue not caught by the local `yaml.safe_load` check — visit the Actions tab in the GitHub UI to read the parse error.

- [ ] **Step 5: Wait for CI to finish, then verify it's green**

Run: `gh pr checks --watch`
Expected (after ~5 min): all rows show `pass`. The matrix produces 3 sanity rows + 1 unit row = 4 checks total.

If any row is red, click through to the Actions tab and read the log; the most likely culprits are:
- `pip install ansible-core==2.X.*` fails: that ansible-core version is no longer on PyPI; remove it from the matrix and bump the minimum further.
- `ansible-test sanity` fails on a rule that's in `tests/sanity/ignore-2.16.txt`: the ignore file needs updating to cover 2.17/2.18 too — copy the relevant lines into new `ignore-2.17.txt` and `ignore-2.18.txt` files, commit, push.
- `pytest tests/unit/` fails: re-run locally with the same Python version to reproduce — the unit tests are pure-Python and should not behave differently in CI.

- [ ] **Step 6: No new commit needed for this task**

The push and PR creation are the deliverable. If CI required follow-up fixes in this step, those will already be on the branch.

---

## Self-Review

**Spec coverage:** Walking the spec section-by-section:
- File layout → Tasks 3 and 4 create both workflow files.
- `test.yml` triggers / concurrency / sanity matrix / unit job → Task 3.
- `release.yml` trigger / concurrency / permissions / guards / build / publish → Task 4.
- Associated repo changes (runtime.yml bump, ignore-file deletes, README) → Tasks 1, 2, 6.
- Setup the maintainer does once → documented in PR body (Task 8) and README CI/CD section (Task 6).
- Testing the workflows (dry-run + first-tag-as-test) → Task 7 + dry-run doc (Task 5) + PR self-test (Task 8).
- Rollback procedure → covered in spec; not a code change so no task needed; mentioned implicitly in the README's "if release.yml fails partway through" paragraph.

**Placeholder scan:** Searched for "TBD", "TODO", "handle edge cases", "similar to Task" — none present. Each step has the exact command or full file content.

**Type/name consistency:** Cross-checked the four name occurrences that travel between tasks:
- Repo-secret name `GALAXY_API_KEY` — same in Task 4 (workflow), Task 6 (README), Task 8 (PR body). ✓
- Tag pattern `v*` — same in Task 4 trigger and Task 8 PR body. ✓
- Matrix versions `'2.16', '2.17', '2.18'` — match `>=2.16.0` in Task 1, ignore-file delete-list in Task 2, README in Task 6. ✓
- Workflow display names: `Test` and `Release` — referenced in PR body's "branch protection" note (Task 8). ✓

One real ambiguity caught: spec talks about "the `Validation` table" but README structure puts that as a section with a table inside. Task 6 says "after the `## Validation` table" — clarified by the `grep -c '^## CI/CD$'` check that ensures we don't double-append.

Plan complete and saved to `docs/superpowers/plans/2026-05-29-cicd-pipeline.md`.
