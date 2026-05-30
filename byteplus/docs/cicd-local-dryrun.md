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
