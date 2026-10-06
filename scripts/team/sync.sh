#!/usr/bin/env bash
# Fast-forward the main checkout after the lead merged PRs.
#
#   .crew/bin/sync.sh [branch]
#
# WP specs are often written in the main checkout and committed through the agent's PR; after the
# merge, the untracked local copy blocks `git pull`. Untracked files that are byte-identical
# (ignoring CRLF) to the incoming version are removed; anything that differs stops the sync.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
branch="${1:-$(git -C "$root" rev-parse --abbrev-ref HEAD)}"
git -C "$root" fetch -q origin
incoming="origin/$branch"
blocked=0
while IFS= read -r path; do
  [[ -n "$path" ]] || continue
  if git -C "$root" cat-file -e "$incoming:$path" 2>/dev/null; then
    if cmp -s <(git -C "$root" show "$incoming:$path" | tr -d '\r') <(tr -d '\r' <"$root/$path"); then
      rm "$root/$path"
      echo "removed local copy (identical upstream): $path"
    else
      echo "differs from upstream, keep and resolve by hand: $path" >&2
      blocked=1
    fi
  fi
done < <(git -C "$root" ls-files --others --exclude-standard)
[[ $blocked -eq 0 ]] || exit 1
stashed=0
if ! git -C "$root" diff --quiet; then git -C "$root" stash -q && stashed=1; fi
git -C "$root" merge -q --ff-only "$incoming"
[[ $stashed -eq 0 ]] || git -C "$root" stash pop -q
git -C "$root" log --oneline -1
