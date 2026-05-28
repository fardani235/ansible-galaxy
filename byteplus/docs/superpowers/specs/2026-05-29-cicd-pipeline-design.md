# CI/CD Pipeline Design

**Date:** 2026-05-29
**Status:** Proposed
**Scope:** GitHub Actions workflows for testing and releasing the `fardani235.byteplus` collection to Ansible Galaxy.

## Goal

Replace the current ad-hoc local testing + manual `ansible-galaxy collection publish` flow with two automated GitHub Actions workflows: one that runs sanity and unit tests on every PR and push to `main`, and one that builds and publishes to Galaxy when a `v*` tag is pushed.

## Background

The collection currently has no CI. Releases happen by running `ansible-galaxy collection build` + `ansible-galaxy collection publish` locally with a token pasted from `~/.ansible/galaxy_token`. This is error-prone in three ways the spec must close:

1. There is no enforced check that what gets published actually passes sanity and unit tests.
2. There is no enforced check that `galaxy.yml` version matches what the release is "supposed" to be.
3. Unfolded changelog fragments can accidentally ship as part of a release tarball, hiding the actual change list from operators.

The collection also declares `requires_ansible: ">=2.14.0"` but is never actually exercised against any version. Adding CI is the right moment to align declared support with tested support.

## Design

### File layout

Two new files under `.github/workflows/`:

```
.github/
  workflows/
    test.yml          # PR + push-to-main
    release.yml       # v* tag push
```

No other files are added or moved under `.github/`. No issue templates, no CODEOWNERS, no Dependabot config — those are independent concerns for a later PR.

### test.yml

**Triggers:**

```yaml
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
```

PRs targeting `main` and merges/direct pushes to `main` are the only triggers. Pushes to other branches (`spec/*`, feature branches) do not run CI — this keeps spec/planning iteration cheap and matches the user's stated preference.

**Concurrency:**

```yaml
concurrency:
  group: test-${{ github.ref }}
  cancel-in-progress: true
```

A new push to the same branch cancels the previous run. Standard GHA pattern.

**Jobs (run in parallel):**

`sanity` — matrix over three ansible-core versions:

```yaml
sanity:
  strategy:
    fail-fast: false
    matrix:
      ansible-version: ['2.16', '2.17', '2.18']
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
      with:
        path: ansible_collections/fardani235/byteplus
    - uses: actions/setup-python@v5
      with:
        python-version: '3.11'
    - run: pip install "ansible-core==${{ matrix.ansible-version }}.*"
    - working-directory: ansible_collections/fardani235/byteplus
      run: ansible-test sanity --docker --python 3.11
```

The checkout path `ansible_collections/fardani235/byteplus` is required by `ansible-test` — sanity refuses to run unless the repo lives at the canonical collection path.

`fail-fast: false` so a failure in one ansible-core version doesn't cancel the others — the operator sees the full matrix result on a red run.

`unit` — single job, no matrix:

```yaml
unit:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
      with:
        path: ansible_collections/fardani235/byteplus
    - uses: actions/setup-python@v5
      with:
        python-version: '3.11'
    - run: pip install ansible-core
    - working-directory: ansible_collections/fardani235/byteplus
      run: |
        pip install -r tests/unit/requirements.txt
        pytest tests/unit/ -v
```

Single ansible-core version for unit tests — pure-Python unit tests don't benefit from the matrix; sanity already exercises argspec compatibility across versions.

### release.yml

**Trigger:**

```yaml
on:
  push:
    tags: ['v*']
```

**Concurrency:**

```yaml
concurrency:
  group: release
  cancel-in-progress: false
```

Single global group — never two releases at once. `cancel-in-progress: false` because cancelling a half-published release could leave Galaxy in an inconsistent state.

**Permissions:**

```yaml
permissions:
  contents: read
```

Read-only. We're not creating GitHub Releases, not pushing back to the repo, not opening PRs — just publishing to an external service with a secret.

**Job — sequential, fail-fast:**

The guards run before any build/publish so a misnamed tag or unfolded fragment is caught before a tarball is produced.

```yaml
release:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
      with:
        path: ansible_collections/fardani235/byteplus

    - uses: actions/setup-python@v5
      with:
        python-version: '3.11'

    - run: pip install ansible-core

    - name: Verify tag matches galaxy.yml version
      working-directory: ansible_collections/fardani235/byteplus
      run: |
        TAG_VERSION="${GITHUB_REF_NAME#v}"
        GALAXY_VERSION="$(grep '^version:' galaxy.yml | awk '{print $2}')"
        if [ "$TAG_VERSION" != "$GALAXY_VERSION" ]; then
          echo "::error::tag $GITHUB_REF_NAME (=$TAG_VERSION) != galaxy.yml version $GALAXY_VERSION"
          exit 1
        fi

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

    - name: Run sanity on tagged commit
      working-directory: ansible_collections/fardani235/byteplus
      run: ansible-test sanity --docker --python 3.11

    - name: Run unit tests on tagged commit
      working-directory: ansible_collections/fardani235/byteplus
      run: |
        pip install -r tests/unit/requirements.txt
        pytest tests/unit/ -v

    - name: Build collection tarball
      working-directory: ansible_collections/fardani235/byteplus
      run: ansible-galaxy collection build --output-path /tmp/dist

    - name: Publish to Ansible Galaxy
      working-directory: ansible_collections/fardani235/byteplus
      run: |
        TAG_VERSION="${GITHUB_REF_NAME#v}"
        ansible-galaxy collection publish \
          "/tmp/dist/fardani235-byteplus-${TAG_VERSION}.tar.gz" \
          --api-key "${{ secrets.GALAXY_API_KEY }}"
```

Pre-publish guards in this order: cheap checks first (tag/version match, fragment check), expensive checks second (sanity, unit), then build, then publish. A failure at any step aborts before the next.

Single-version sanity at release time (2.18, latest) rather than the matrix — the matrix already ran on the merge-to-main commit. The release-time sanity is a "did anything land between merge and tag" guard, not a compatibility sweep.

### Associated repo changes (same PR)

Three edits outside `.github/`:

1. **`meta/runtime.yml`** — bump `requires_ansible` from `">=2.14.0"` to `">=2.16.0"`. The matrix is the source of truth; the declared minimum must match.

2. **`tests/sanity/ignore-2.14.txt` and `tests/sanity/ignore-2.15.txt`** — delete. Keep `tests/sanity/ignore-2.16.txt`. Carrying ignore files for versions we don't test invites bit-rot when a sanity rule fires on a version no one runs.

3. **`README.md`** — add a short "CI/CD" section at the bottom (after the existing `## Validation` section) explaining: (a) the two workflows and what triggers them, (b) the release flow ("bump `galaxy.yml`, fold fragments, tag `vX.Y.Z`, push tag"), (c) the GALAXY_API_KEY secret requirement. Three to four sentences.

### Setup the maintainer does once, outside this PR

1. Generate a Galaxy API token at https://galaxy.ansible.com → preferences → API key.
2. Add it as repo secret `GALAXY_API_KEY` (Settings → Secrets and variables → Actions).
3. Optional: branch protection on `main` requiring `test.yml` to pass before merge. Without this, CI runs but doesn't block — a red CI does not stop the merge button.

No GitHub App, no OIDC trusted publishing, no Galaxy namespace claim — the namespace `fardani235` is already owned.

## Testing the workflows

`test.yml` self-tests as soon as it's pushed: the PR that adds it runs it on itself. If the PR is green, the workflow itself works.

`release.yml` is harder to verify without a real publish. Two-step shake-out:

1. **Dry-run the guards locally** before merging the workflow PR — run the `verify tag matches galaxy.yml` and `verify no unfolded fragments` bash blocks against the current checkout to confirm they pass on a clean state and fail on a hand-crafted bad state (e.g. a stub fragment file in `changelogs/fragments/`).
2. **First real tag is the live test.** Tag `v1.2.0` only after this PR is merged to main and `test.yml` is green there. If `release.yml` fails partway through, fix the workflow and re-tag `v1.2.1` — Galaxy rejects re-uploads of the same version, so a failed publish never leaves a partial-state artifact on Galaxy.

## Rollback

If a bad publish lands on Galaxy:

- `ansible-galaxy collection deprecate fardani235.byteplus:X.Y.Z` marks the version as deprecated; consumers see a warning and don't pull it by default. Full deletion requires Galaxy admin intervention and is rarely needed.
- For the repo: revert the release commit on main, bump `galaxy.yml` to the next patch version, fold a changelog fragment describing the issue, tag the new patch. The bad tag stays in git history; that's fine.

## Out of scope

Explicitly not included in this design:

- **Integration / smoke tests in CI.** The smoke playbook hits real BytePlus IAM and costs money/quota; it stays a manual maintainer step. Sanity + unit catch the categories of regressions CI is best at catching.
- **GitHub Release creation.** Galaxy is the canonical distribution channel for Ansible collections; an additional GitHub Release adds maintenance burden with no consumer benefit.
- **Dependabot, CODEOWNERS, issue templates, PR templates.** Independent concerns.
- **OIDC trusted publishing.** Galaxy's OIDC support is still maturing as of 2026-05; the repo-secret approach is the well-trodden path and can be migrated later without breaking the release flow.
- **Multiple Python versions in the matrix.** Python 3.11 is supported across all three ansible-core versions in the matrix; adding more Python versions multiplies CI cost without catching realistic bugs.

## Decision log

| Decision | Choice | Why |
|----------|--------|-----|
| Platform | GitHub Actions | Repo lives on GitHub; first-party integration; no extra service |
| Test scope in CI | sanity + unit only | Smoke playbook needs live BytePlus credentials and incurs cost |
| ansible-core matrix | 2.16, 2.17, 2.18 | Current actively-supported versions; matches `requires_ansible` bump |
| Release trigger | `v*` tag push | Explicit, auditable, decouples release from merge |
| Galaxy auth | Repo secret `GALAXY_API_KEY` | Simplest secure approach; OIDC can come later |
| GitHub Release asset | No | Galaxy is the canonical distribution channel |
| Pre-publish guards | tag==galaxy.yml + sanity+unit + folded fragments | Each closes a real release-time mistake |
| Branch triggers | PRs to main + pushes to main | Spec/feature branches don't need CI noise |
