#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
#
# Upload a release that packaging/release.py assembled, as a draft on GitHub. You review it
# there and press Publish.
#
#   packaging/publish.sh dist/release/v1.0.0
#
# It asks for a GitHub token: a fine-grained personal access token for this repository only,
# with "Contents: Read and write". The token is never shown, saved, or put on a command line.
# Needs curl and jq. The tag must already be pushed and point at the commit the files were
# built from. Running it again resumes: files already on the draft are skipped.
set -euo pipefail

REPO="s7u512/wavematerial"
API="https://api.github.com/repos/$REPO"
UPLOADS="https://uploads.github.com/repos/$REPO"

die() { echo "publish.sh: $*" >&2; exit 1; }

dir="${1:-}"
[[ -n "$dir" && -d "$dir" ]] || die "usage: packaging/publish.sh dist/release/vX.Y.Z"
tag="$(basename "$dir")"
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "$dir is not a dist/release/vX.Y.Z folder"
for f in SHA256SUMS RELEASE_NOTES.md COMMIT; do
    [[ -f "$dir/$f" ]] || die "$dir has no $f; run packaging/release.py"
done
command -v curl >/dev/null && command -v jq >/dev/null || die "needs curl and jq"

echo "Checking the files against SHA256SUMS..."
(cd "$dir" && sha256sum --check --quiet SHA256SUMS) || die "checksums don't match"

commit="$(cat "$dir/COMMIT")"
remote="$(git ls-remote origin "refs/tags/$tag^{}" | cut -f1)"
[[ -n "$remote" ]] || remote="$(git ls-remote origin "refs/tags/$tag" | cut -f1)"
[[ -n "$remote" ]] || die "tag $tag is not on origin; push it first"
[[ "$remote" == "$commit" ]] || die "tag $tag on origin is $remote, but the files were built from $commit"

read -rsp "GitHub token for $REPO (input hidden): " TOKEN
echo
[[ -n "$TOKEN" ]] || die "no token given"

# The token reaches curl through a config on a pipe, never through its arguments.
api() {
    curl --fail-with-body --silent --show-error \
        --config <(printf 'header = "Authorization: Bearer %s"\n' "$TOKEN") \
        -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" "$@"
}

# Reuse a draft for this tag if one exists; refuse if the release is already published.
releases="$(api "$API/releases?per_page=100")"
existing="$(jq -c --arg t "$tag" 'map(select(.tag_name == $t)) | first // empty' <<<"$releases")"
if [[ -n "$existing" ]]; then
    [[ "$(jq -r .draft <<<"$existing")" == "true" ]] || die "release $tag is already published"
    id="$(jq -r .id <<<"$existing")"
    echo "Resuming the existing draft for $tag."
else
    body="$(jq -n --arg t "$tag" --arg c "$commit" --rawfile notes "$dir/RELEASE_NOTES.md" \
        '{tag_name: $t, target_commitish: $c, name: ("WaveMaterial " + ($t | ltrimstr("v"))),
          body: $notes, draft: true, prerelease: false}')"
    created="$(api -X POST "$API/releases" -d "$body")"
    id="$(jq -r .id <<<"$created")"
    echo "Created a draft release for $tag."
fi

have="$(api "$API/releases/$id/assets?per_page=100" | jq -r '.[].name')"
for f in "$dir"/*; do
    name="$(basename "$f")"
    [[ "$name" == "RELEASE_NOTES.md" || "$name" == "COMMIT" ]] && continue
    if grep -qxF "$name" <<<"$have"; then
        echo "  $name: already uploaded"
        continue
    fi
    echo "  uploading $name ($(du -h "$f" | cut -f1))..."
    api -X POST -H "Content-Type: application/octet-stream" --upload-file "$f" \
        "$UPLOADS/releases/$id/assets?name=$(jq -rn --arg n "$name" '$n | @uri')" >/dev/null
done
unset TOKEN

echo
echo "Done. The draft is on https://github.com/$REPO/releases (visible only to you for now)."
echo "Look it over there and press Publish release."
