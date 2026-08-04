#!/usr/bin/env bash
# Prove every SHA pin is a real commit AND matches the version named in its comment.
grep -rhoE "uses: [a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+@[0-9a-f]{40} # \S+" .github/workflows/ \
  | sort -u | while read -r _ spec _ ver; do
  repo="${spec%@*}"; sha="${spec##*@}"
  commit=$(gh api "repos/$repo/commits/$sha" --jq '.sha' 2>/dev/null)
  ref=$(gh api "repos/$repo/git/ref/tags/$ver" --jq '.object.sha + " " + .object.type' 2>/dev/null)
  tag="${ref%% *}"; kind="${ref##* }"
  # An annotated tag points at a tag object, not the commit — dereference it, or the
  # comparison silently fails for exactly the action that holds the secret.
  [ "$kind" = "tag" ] && tag=$(gh api "repos/$repo/git/tags/$tag" --jq '.object.sha' 2>/dev/null)
  if [ "$commit" = "$sha" ] && [ "$tag" = "$sha" ]; then
    printf '  OK    %-34s %-9s real commit, matches tag\n' "$repo" "$ver"
  else
    printf '  FAIL  %-34s %-9s commit=%s tag=%s\n' "$repo" "$ver" "$commit" "$tag"
  fi
done
