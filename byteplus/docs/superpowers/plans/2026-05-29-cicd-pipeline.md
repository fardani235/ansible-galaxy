# CI/CD Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two GitHub Actions workflows (`test.yml` for PRs and pushes to `main`, `release.yml` for `byteplus-v*` tag pushes), bump the collection's declared minimum ansible-core version to match what we test, drop stale sanity ignore files, and document the release flow.

**Architecture:** This is a monorepo (`github.com/fardani235/ansible-galaxy`) with the collection under `byteplus/`. The workflow files live at the **monorepo root** (`.github/workflows/`) because GHA only reads workflows from the repo root, not from subdirectories. Both workflows are paths-filtered to `byteplus/**` so they don't fire on unrelated monorepo changes. Sanity needs the canonical `ansible_collections/<ns>/<name>` layout, achieved by checking out into `src/` and symlinking. Release tags use a `byteplus-v*` prefix so future sibling collections can use their own namespaced tags.

**Tech Stack:** GitHub Actions, `actions/checkout@v4`, `actions/setup-python@v5`, `ansible-core` (pip-installed), `ansible-test sanity --docker`, `pytest`, `ansible-galaxy collection build`, `ansible-galaxy collection publish`.

**Reference spec:** `byteplus/docs/superpowers/specs/2026-05-29-cicd-pipeline-design.md` (amended at commit `d34f4b3` to reflect the monorepo layout)

---

## Important: paths in this plan

All paths are given relative to the **monorepo root** (`/home/ridwan/workspace/ansible_galaxy/`), NOT relative to `byteplus/`. The collection's `git rev-parse --show-prefix` returns `byteplus/`, so commands run from inside the collection need to either `cd ..` first or use a path with the `byteplus/` prefix. When in doubt, run `pwd` — the monorepo root contains `.git/` and `byteplus/` as siblings.

## File Map

What this plan creates, modifies, and deletes (paths relative to monorepo root):

- **Create:** `.github/workflows/test.yml` — at monorepo root, PR + push-to-main test workflow
- **Create:** `.github/workflows/release.yml` — at monorepo root, `byteplus-v*` tag publish workflow
- **Create:** `byteplus/docs/cicd-local-dryrun.md` — local dry-run reference for the release guards
- **Modify:** `byteplus/meta/runtime.yml` — bump `requires_ansible` from `">=2.14.0"` to `">=2.16.0"` (DONE in Task 1)
- **Modify:** `byteplus/README.md` — append `## CI/CD` section after the existing `## Validation` table
- **Delete:** `byteplus/tests/sanity/ignore-2.14.txt` (DONE in Task 2)
- **Delete:** `byteplus/tests/sanity/ignore-2.15.txt` (DONE in Task 2)

Out of scope (per spec): integration / smoke tests in CI, GitHub Release creation, OIDC trusted publishing, Dependabot, CODEOWNERS, multi-Python matrix, the monorepo root `README.md` (intentionally empty), `galaxy.yml` version bump (lives on a separate branch).

---

## Branch

Work happens on `spec/cicd-pipeline` (already current). Tasks 1 and 2 are already committed. All remaining tasks commit onto this branch.

---

### Task 1: Bump declared ansible-core minimum [DONE]

Already done at commit `c757a13`. Bumped `byteplus/meta/runtime.yml` `requires_ansible` from `">=2.14.0"` to `">=2.16.0"`.

---

### Task 2: Delete sanity ignore files for dropped ansible-core versions [DONE]

Already done at commit `8db4ce6`. Deleted `byteplus/tests/sanity/ignore-2.14.txt` and `byteplus/tests/sanity/ignore-2.15.txt`. Kept `byteplus/tests/sanity/ignore-2.16.txt`.

---

### Task 3: Write the test.yml workflow at monorepo root

The PR-and-push CI: sanity matrix (2.16/2.17/2.18) plus a unit job, parallel, paths-filtered to `byteplus/**`, with `cancel-in-progress` concurrency per branch.

**Files:**
- Create: `.github/workflows/test.yml` (at monorepo root — `/home/ridwan/workspace/ansible_galaxy/.github/workflows/test.yml`)

**Pre-step: confirm working directory**

Before any step in this task, confirm you're at the monorepo root:

```bash
cd /home/ridwan/workspace/ansible_galaxy
pwd            # must print /home/ridwan/workspace/ansible_galaxy
ls -d .git byteplus    # both must exist
```

If `pwd` instead prints `/home/ridwan/workspace/ansible_galaxy/byteplus`, `cd ..` first.

- [ ] **Step 1: Ensure the workflow directory exists at monorepo root**

Run (from monorepo root): `mkdir -p .github/workflows`

Verify: `ls -d .github/workflows` succeeds and is at the monorepo root (the parent of this directory must contain both `.git/` and `byteplus/`).

- [ ] **Step 2: Write the full file**

Create `.github/workflows/test.yml` (at the monorepo root, NOT under `byteplus/`) with exactly this content:

```yaml
name: Test

on:
  pull_request:
    branches: [main]
    paths:
      - 'byteplus/**'
      - '.github/workflows/test.yml'
  push:
    branches: [main]
    paths:
      - 'byteplus/**'
      - '.github/workflows/test.yml'

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
      - name: Check out monorepo
        uses: actions/checkout@v4
        with:
          path: src

      - name: Symlink collection into ansible_collections path
        run: |
          mkdir -p ansible_collections/fardani235
          ln -s "$GITHUB_WORKSPACE/src/byteplus" ansible_collections/fardani235/byteplus

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
      - name: Check out monorepo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install ansible-core
        run: pip install ansible-core

      - name: Install unit test requirements
        working-directory: byteplus
        run: pip install -r tests/unit/requirements.txt

      - name: Run pytest
        working-directory: byteplus
        run: pytest tests/unit/ -v
```

- [ ] **Step 3: Validate YAML syntax**

Run (from monorepo root): `python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))"`
Expected: no output, exit code 0.

- [ ] **Step 4: Confirm file is at monorepo root, not under byteplus/**

Run from monorepo root: `git ls-files --others --exclude-standard .github/workflows/`
Expected output: `.github/workflows/test.yml`

Also check: `find . -name 'test.yml' -path '*/workflows/*'`
Expected output: `./.github/workflows/test.yml` (and NOT `./byteplus/.github/workflows/test.yml`).

If you see the path under `byteplus/`, you wrote it in the wrong place — `rm byteplus/.github/workflows/test.yml` and rmdir up the empty parents, then go back to Step 2.

- [ ] **Step 5: Commit (from monorepo root)**

```bash
cd /home/ridwan/workspace/ansible_galaxy
git add .github/workflows/test.yml
git commit -m "ci: add test workflow at monorepo root for PRs and pushes to main

Runs ansible-test sanity across ansible-core 2.16/2.17/2.18 in parallel
plus a single unit-test job. Paths-filtered to byteplus/** so changes
elsewhere in the monorepo do not trigger this collection's CI. Per-branch
concurrency with cancel-in-progress keeps CI minutes down when pushes
stack up. Sanity uses a checkout-into-src/ + symlink-into-ansible_collections/
layout so ansible-test sees the canonical collection path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Write the release.yml workflow at monorepo root

The `byteplus-v*`-tag publish workflow with pre-publish guards (tag↔galaxy.yml match, folded changelog fragments, sanity, unit) running before build and publish.

**Files:**
- Create: `.github/workflows/release.yml` (at monorepo root)

**Pre-step: confirm working directory**

```bash
cd /home/ridwan/workspace/ansible_galaxy
pwd            # must be /home/ridwan/workspace/ansible_galaxy
ls -d .github/workflows    # already exists from Task 3
```

- [ ] **Step 1: Write the full file**

Create `.github/workflows/release.yml` (at monorepo root) with exactly this content:

```yaml
name: Release

on:
  push:
    tags: ['byteplus-v*']

concurrency:
  group: release-byteplus
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  release:
    name: Build and publish to Ansible Galaxy
    runs-on: ubuntu-latest
    steps:
      - name: Check out monorepo at tag
        uses: actions/checkout@v4
        with:
          path: src

      - name: Symlink collection into ansible_collections path
        run: |
          mkdir -p ansible_collections/fardani235
          ln -s "$GITHUB_WORKSPACE/src/byteplus" ansible_collections/fardani235/byteplus

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install ansible-core
        run: pip install ansible-core

      - name: Verify tag matches galaxy.yml version
        working-directory: ansible_collections/fardani235/byteplus
        run: |
          TAG_VERSION="${GITHUB_REF_NAME#byteplus-v}"
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
          TAG_VERSION="${GITHUB_REF_NAME#byteplus-v}"
          ansible-galaxy collection publish \
            "/tmp/dist/fardani235-byteplus-${TAG_VERSION}.tar.gz" \
            --api-key "$GALAXY_API_KEY"
```

`GALAXY_API_KEY` is passed via the `env:` block rather than interpolated directly into the run script — keeps the secret out of the rendered command line that shows up in GHA logs even if `set -x` gets turned on later.

- [ ] **Step 2: Validate YAML syntax**

Run from monorepo root: `python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"`
Expected: no output, exit code 0.

- [ ] **Step 3: Confirm file location**

Run from monorepo root: `find . -name 'release.yml' -path '*/workflows/*'`
Expected output: `./.github/workflows/release.yml` (NOT under `byteplus/`).

- [ ] **Step 4: Commit (from monorepo root)**

```bash
cd /home/ridwan/workspace/ansible_galaxy
git add .github/workflows/release.yml
git commit -m "ci: add release workflow triggered by byteplus-v* tag push

Pre-publish guards run in cheap-to-expensive order: tag<->galaxy.yml
version match, folded-fragment check, sanity, unit, then build, then
publish. Tag pattern is byteplus-v* (not v*) to namespace this
collection in the monorepo so sibling collections can use their own
prefixed tags later. GALAXY_API_KEY is piped via env so it doesn't
appear in the rendered command line.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Write the local-dryrun doc for the release guards

Operators need to verify the release guards locally before pushing a tag. Doc lives in the collection (`byteplus/docs/`), since it's documentation about this collection's release flow.

**Files:**
- Create: `byteplus/docs/cicd-local-dryrun.md`

**Pre-step: confirm working directory**

```bash
cd /home/ridwan/workspace/ansible_galaxy/byteplus
pwd     # must be /home/ridwan/workspace/ansible_galaxy/byteplus
```

- [ ] **Step 1: Write the doc**

Create `byteplus/docs/cicd-local-dryrun.md` (from anywhere, using an absolute path or, if you're in `byteplus/`, the relative path `docs/cicd-local-dryrun.md`) with this content:

````markdown
# Dry-running the release guards locally

Before you push a `byteplus-vX.Y.Z` tag, run these exact checks from
inside the `byteplus/` collection directory. They mirror what
`.github/workflows/release.yml` runs in CI; if they pass here they
should pass there.

```bash
cd byteplus    # from monorepo root, all commands below run from here
```

## 1. Tag-name vs galaxy.yml version match

Set `TAG_VERSION` to the version you intend to tag (without the
`byteplus-v` prefix), then:

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
into `CHANGELOG.rst`, commit the result, then re-run.

## 3. Sanity + unit

These are the same commands CI runs (CI does the `ansible_collections/`
symlink dance for sanity; locally, the simplest equivalent is to run
ansible-test from inside the collection — it will tell you if it can't
find the right layout):

```bash
ansible-test sanity --docker --python 3.11
pip install -r tests/unit/requirements.txt
pytest tests/unit/ -v
```

If all three sections pass, the release workflow should pass too. Tag
and push (from the monorepo root):

```bash
cd ..   # back to monorepo root
git tag "byteplus-v${TAG_VERSION}"
git push origin "byteplus-v${TAG_VERSION}"
```
````

- [ ] **Step 2: Verify the doc renders**

Run from monorepo root: `head -3 byteplus/docs/cicd-local-dryrun.md`
Expected: starts with `# Dry-running the release guards locally`.

- [ ] **Step 3: Commit (from monorepo root)**

```bash
cd /home/ridwan/workspace/ansible_galaxy
git add byteplus/docs/cicd-local-dryrun.md
git commit -m "docs: how to dry-run the release guards locally

Mirrors the exact bash blocks release.yml runs so maintainers can
catch a misnamed tag or unfolded fragment before pushing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Add the CI/CD section to the collection's README

Operator-facing doc of what the workflows do, when they fire, and the GALAXY_API_KEY requirement.

**Files:**
- Modify: `byteplus/README.md` (the collection's README, NOT the monorepo root `README.md` which is intentionally empty)

**Pre-step: confirm working directory**

```bash
cd /home/ridwan/workspace/ansible_galaxy
ls byteplus/README.md          # must exist
test -s README.md && echo "MONOREPO README HAS CONTENT" || echo "OK: monorepo README is empty"
```

Expected: `OK: monorepo README is empty`. If it says "MONOREPO README HAS CONTENT", stop and re-read the spec — that file is intentionally empty per the spec; somebody has put content in it that we'd be ignoring here.

- [ ] **Step 1: Confirm append location**

Run from monorepo root: `tail -3 byteplus/README.md`
Expected: last lines of the existing `## Validation` table.

Also run: `grep -c '^## Validation$' byteplus/README.md`
Expected: `1`.

- [ ] **Step 2: Append the section**

Append exactly this content to the end of `byteplus/README.md` (note the leading blank line so the new heading is separated from the table):

```markdown

## CI/CD

This collection ships two GitHub Actions workflows at the **monorepo
root** under `.github/workflows/` (one level above the `byteplus/`
collection directory, because GHA only reads workflows from the repo
root):

- **`test.yml`** runs on pull requests to `main` and pushes to `main`,
  paths-filtered to `byteplus/**` so it only fires on changes to this
  collection. It runs `ansible-test sanity` across ansible-core 2.16,
  2.17, and 2.18 in parallel plus a single `pytest tests/unit/` job.
  Failure on any matrix cell does not cancel the others
  (`fail-fast: false`).
- **`release.yml`** runs on `byteplus-v*` tag pushes (the
  `byteplus-` prefix namespaces the tag so future sibling collections
  can use their own prefixes). It verifies the tag matches `galaxy.yml`
  version, verifies no unfolded `changelogs/fragments/*.yml` remain,
  re-runs sanity + unit on the tagged commit, builds the collection
  with `ansible-galaxy collection build`, then publishes to Ansible
  Galaxy. The Galaxy API token is supplied via the repo secret
  `GALAXY_API_KEY` (Settings → Secrets and variables → Actions).

**To cut a release:**

1. Bump `version:` in `byteplus/galaxy.yml`.
2. Run `antsibull-changelog release` from inside `byteplus/` to fold
   pending fragments into the changelog. Commit.
3. (Optional, recommended) Run the local dry-run from
   `byteplus/docs/cicd-local-dryrun.md` to verify the release guards
   pass.
4. From the monorepo root, tag with the version prefixed by
   `byteplus-v` (e.g. `byteplus-v1.2.0`) and push:
   `git tag byteplus-v1.2.0 && git push origin byteplus-v1.2.0`.

If `release.yml` fails partway through, fix the issue and re-tag with
the next patch version — Galaxy rejects re-uploads of the same version
number, so a failed publish never leaves a partial artifact on Galaxy.
```

You can do this with: `cat >> byteplus/README.md <<'EOF'`-style heredoc (from monorepo root), or via the Edit/Write tool. Either way, the final file must end with the snippet above.

- [ ] **Step 3: Verify the append**

Run from monorepo root: `tail -3 byteplus/README.md`
Expected: ends with the paragraph beginning `If \`release.yml\` fails partway through, ...`.

Also run: `grep -c '^## CI/CD$' byteplus/README.md`
Expected: `1`.

- [ ] **Step 4: Commit (from monorepo root)**

```bash
cd /home/ridwan/workspace/ansible_galaxy
git add byteplus/README.md
git commit -m "docs: add CI/CD section explaining test and release workflows

Documents both workflows, their monorepo location, when they trigger,
and the release procedure (galaxy.yml bump -> fold fragments -> tag
byteplus-vX.Y.Z -> push). Points operators at
byteplus/docs/cicd-local-dryrun.md for the pre-tag verification.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Local dry-run the release guard bash blocks

Verify the two guard blocks from `release.yml` work correctly against the current checkout. This is the spec's "Testing the workflows" item.

**Files:** (no file changes — verification only)

**Pre-step:**

```bash
cd /home/ridwan/workspace/ansible_galaxy/byteplus
pwd      # must be the collection dir; guards reference relative paths within it
```

- [ ] **Step 1: Verify the tag↔galaxy.yml guard catches a mismatch**

Run with an intentionally wrong tag version:

```bash
TAG_VERSION="9.9.9"
GALAXY_VERSION="$(grep '^version:' galaxy.yml | awk '{print $2}')"
if [ "$TAG_VERSION" != "$GALAXY_VERSION" ]; then
  echo "FAIL (expected): tag $TAG_VERSION != galaxy.yml $GALAXY_VERSION"
fi
```

Expected output: `FAIL (expected): tag 9.9.9 != galaxy.yml <current>`.

- [ ] **Step 2: Verify the tag↔galaxy.yml guard passes on a match**

```bash
TAG_VERSION="$(grep '^version:' galaxy.yml | awk '{print $2}')"
GALAXY_VERSION="$(grep '^version:' galaxy.yml | awk '{print $2}')"
if [ "$TAG_VERSION" != "$GALAXY_VERSION" ]; then
  echo "FAIL"
else
  echo "OK"
fi
```

Expected: `OK`.

- [ ] **Step 3: Verify the changelog-fragment guard passes on the current clean state**

```bash
UNFOLDED=$(find changelogs/fragments -type f \
  \( -name '*.yml' -o -name '*.yaml' \) \
  ! -name '.placeholder' 2>/dev/null || true)
if [ -n "$UNFOLDED" ]; then
  echo "FAIL: unfolded:"
  echo "$UNFOLDED"
else
  echo "OK: no unfolded fragments"
fi
```

Expected: `OK: no unfolded fragments`.

If this fails, flag it to the maintainer — there are real unfolded fragments on the branch and they're not caused by this PR.

- [ ] **Step 4: Verify the changelog-fragment guard catches an unfolded fragment**

Stage a fake fragment to confirm the guard would fail at release time:

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
fi
rm -f changelogs/fragments/test-guard.yml
```

Expected output: `FAIL (expected): ...` listing `changelogs/fragments/test-guard.yml`. The test file is removed at the end regardless.

- [ ] **Step 5: Confirm working tree is clean**

From monorepo root: `git status`
Expected: `nothing to commit, working tree clean`.

If `byteplus/changelogs/fragments/test-guard.yml` is listed as untracked, manually `rm` it.

- [ ] **Step 6: No commit needed**

This task makes no file changes.

---

### Task 8: Push the branch and open the PR

Push the branch to origin and open the PR. `test.yml` self-tests against the PR (the PR touches both `byteplus/**` AND `.github/workflows/test.yml`, both of which match the paths filter, so it will fire).

**Files:** (no file changes)

**Pre-step:**

```bash
cd /home/ridwan/workspace/ansible_galaxy
git status     # must be clean
git branch --show-current     # must print spec/cicd-pipeline
```

- [ ] **Step 1: Verify branch state**

Run from monorepo root: `git log --oneline main..HEAD`
Expected: 7 or 8 commits — the spec commit, the spec amendment commit (`d34f4b3`), the plan commit, plus Tasks 1, 2, 3, 4, 5, 6. (Task 7 made no commit. The exact count depends on whether you separated plan and spec into one or two commits.)

Confirm none of the file changes leak outside the intended locations:

```bash
git diff --name-only main..HEAD
```

Expected paths (in some order):
- `byteplus/docs/superpowers/specs/2026-05-29-cicd-pipeline-design.md`
- `byteplus/docs/superpowers/plans/2026-05-29-cicd-pipeline.md`
- `byteplus/meta/runtime.yml`
- `byteplus/tests/sanity/ignore-2.14.txt` (deleted)
- `byteplus/tests/sanity/ignore-2.15.txt` (deleted)
- `.github/workflows/test.yml`
- `.github/workflows/release.yml`
- `byteplus/docs/cicd-local-dryrun.md`
- `byteplus/README.md`

If any file outside this list is changed, investigate before pushing.

- [ ] **Step 2: Push the branch**

```bash
cd /home/ridwan/workspace/ansible_galaxy
git push -u origin spec/cicd-pipeline
```

If `gh` is not authenticated yet, the maintainer needs to authenticate first (in their own terminal: `gh auth login`).

- [ ] **Step 3: Open the PR**

Run from monorepo root:

```bash
gh pr create \
  --base main \
  --head spec/cicd-pipeline \
  --title "ci: add test + release workflows for Ansible Galaxy publishing" \
  --body "$(cat <<'EOF'
## Summary

Adds GitHub Actions CI/CD per spec
`byteplus/docs/superpowers/specs/2026-05-29-cicd-pipeline-design.md`:

- **`.github/workflows/test.yml`** — at monorepo root. Runs on PRs to
  main and pushes to main, paths-filtered to `byteplus/**`. Matrix
  sanity (ansible-core 2.16/2.17/2.18) + single unit job, parallel,
  `cancel-in-progress` per branch.
- **`.github/workflows/release.yml`** — at monorepo root. Runs on
  `byteplus-v*` tag push (collection-namespaced for future sibling
  collections). Pre-publish guards (tag↔galaxy.yml match, folded
  changelog fragments, sanity, unit) run before build and publish to
  Ansible Galaxy via the `GALAXY_API_KEY` repo secret.

## Associated collection changes

- `byteplus/meta/runtime.yml`: `requires_ansible` bumped from
  `>=2.14.0` to `>=2.16.0` to match the matrix.
- `byteplus/tests/sanity/ignore-2.14.txt` and `ignore-2.15.txt`
  deleted (we no longer test those versions).
- `byteplus/README.md`: new `## CI/CD` section documenting both
  workflows and the release procedure.
- `byteplus/docs/cicd-local-dryrun.md`: pre-tag verification commands.

## Setup required before first release

1. Generate a Galaxy API token at https://galaxy.ansible.com
   (preferences → API key).
2. Add it as repo secret `GALAXY_API_KEY` (Settings → Secrets and
   variables → Actions).
3. Recommended: branch protection on `main` requiring the `Test`
   workflow checks to pass.

## Testing

Pre-publish guard bash blocks were dry-run locally against this branch
(Task 7 of the plan); both positive and negative cases behave as
expected. `test.yml` self-tests as soon as this PR opens — if CI on
this PR is green, the test workflow itself works.

`release.yml` is verified by the live first-tag (`byteplus-v1.2.0`,
after the IAM PR merges). Galaxy rejects re-uploads of the same
version, so a failed publish never corrupts the registry.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Verify the PR opened and CI started**

```bash
gh pr view --json url,statusCheckRollup
```

Expected: a URL to the PR; `statusCheckRollup` shows workflows as `IN_PROGRESS` or `PENDING`.

If `statusCheckRollup` is empty (no checks listed), GitHub may have rejected the workflow files for a syntax issue not caught by the local `yaml.safe_load` check, OR the paths filter excluded this PR. Check the Actions tab in the GitHub UI; also confirm at least one path-matched file is in the PR diff (the workflow file itself counts).

- [ ] **Step 5: Wait for CI to finish, then verify it's green**

```bash
gh pr checks --watch
```

Expected (after ~5 min): all rows show `pass`. The matrix produces 3 sanity rows + 1 unit row = 4 checks.

Likely failure modes:
- `pip install ansible-core==2.X.*` fails: that version is no longer on PyPI; remove from matrix and bump the declared minimum in `byteplus/meta/runtime.yml` further.
- `ansible-test sanity` fails on a rule that's in `byteplus/tests/sanity/ignore-2.16.txt`: copy relevant lines into new `ignore-2.17.txt` / `ignore-2.18.txt` files, commit, push.
- `pytest tests/unit/` fails: reproduce locally with the same Python version. Unit tests are pure-Python and should not behave differently in CI.

- [ ] **Step 6: No new commit needed for this task**

The push and PR creation are the deliverable. If CI required follow-up fixes, those would already be on the branch.

---

## Self-Review (after spec amendment)

Re-checking the plan against the amended spec:

**Spec coverage:**
- File layout (monorepo root `.github/workflows/` + paths filter) → Tasks 3 and 4.
- `test.yml` triggers / paths / concurrency / sanity matrix with symlink hop / unit job → Task 3.
- `release.yml` `byteplus-v*` trigger / concurrency / permissions / guards / build / publish via env-block secret → Task 4.
- Associated collection changes (runtime.yml bump, ignore-file deletes, `byteplus/README.md`) → Tasks 1, 2, 6.
- `byteplus/docs/cicd-local-dryrun.md` → Task 5.
- Maintainer one-time setup → Task 6 README content + Task 8 PR body.
- Testing the workflows (dry-run + first-tag-as-test) → Task 7 + dry-run doc (Task 5) + PR self-test (Task 8).
- Rollback procedure → mentioned in spec; documented implicitly in README CI/CD section ("if release.yml fails partway through").

**Placeholder scan:** No TBD/TODO/vague items.

**Type/name consistency:**
- Repo-secret name `GALAXY_API_KEY` — same in Tasks 4, 6, 8.
- Tag pattern `byteplus-v*` — same in Task 4 trigger, Task 5 dryrun doc, Task 6 README, Task 8 PR body.
- Matrix versions `'2.16', '2.17', '2.18'` — match `>=2.16.0` in Task 1, ignore-file deletions in Task 2, README in Task 6.
- Workflow display names `Test` and `Release` — referenced in Task 8 PR body's branch protection note.
- Concurrency group `release-byteplus` (Task 4) vs `release` from earlier draft — updated for monorepo future-proofing.
