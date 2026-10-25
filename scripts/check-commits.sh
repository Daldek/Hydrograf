#!/usr/bin/env bash
# Commit step of the gate (DEV-4.1 to DEV-4.5), from Nogat
# standards/ci/check-commits.sh. Copy unchanged to scripts/check-commits.sh;
# scripts/gate.sh calls it as its last step.
#
# Environment:
#   GATE_COMMIT_RANGE  commits to check, e.g. "origin/develop..HEAD"; "none"
#                      skips the step. CI sets it (DEV-4.5). Unset means a
#                      local run: the identity preflight runs (with the author
#                      check) and the range is the unpushed commits, else the
#                      commits since origin/develop, else HEAD only.
#   GATE_AUTHOR_EMAIL  required author e-mail (default git@debever.pl)
#   GATE_CHECK_AUTHOR  1 (default) checks the author (DEV-4.2); contributors
#                      run with 0, and CI sets 0 for forks and Dependabot,
#                      whose commits keep their own identity (DEV-16.5)
set -euo pipefail

email="${GATE_AUTHOR_EMAIL:-git@debever.pl}"
range="${GATE_COMMIT_RANGE:-}"

if [[ "$range" == none ]]; then
  printf '  skipped (GATE_COMMIT_RANGE=none)\n'
  exit 0
fi

if [[ -z "$range" ]]; then
  if [[ "${GATE_CHECK_AUTHOR:-1}" == 1 ]]; then
    # Identity preflight: the commit about to be made cannot be checked yet,
    # but the identity git will give it can.
    ident="$(git var GIT_AUTHOR_IDENT 2>/dev/null || true)"
    if [[ "$ident" != *"<$email>"* ]]; then
      shown="${ident% * *}"
      printf 'check-commits: git would commit as "%s", expected <%s> (DEV-4.2)\n' \
        "${shown:-no identity}" "$email" >&2
      printf '  fix: git config user.name Daldek && git config user.email %s\n' \
        "$email" >&2
      exit 1
    fi
  fi
  if ! git rev-parse --verify --quiet HEAD >/dev/null; then
    printf '  no commits yet\n'
    exit 0
  fi
  if git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
    range='@{upstream}..HEAD'
  elif base="$(git merge-base HEAD origin/develop 2>/dev/null)"; then
    range="$base..HEAD"
  else
    range='HEAD^!'
  fi
fi

if ! commits="$(git rev-list "$range" 2>/dev/null)"; then
  printf 'check-commits: range %s not available (fetch the full history)\n' "$range" >&2
  exit 1
fi

subject_re='^(feat|fix|docs|test|refactor|perf|style|build|ci|chore)(\([^)]+\))?!?: .+'
# AI attribution (DEV-4.3): a co-author trailer whose name starts with an AI
# tool or whose e-mail belongs to one, a session line, a "Generated with
# <tool>" line, or the robot emoji. A person who merely shares a word with a
# tool ("Jan Gemini <jan@gemini.pl>") and prose mentioning a tool pass.
tools='(claude|anthropic|copilot|openai|chatgpt|gpt|gemini|cursor|codex|aider|devin)'
domains='(anthropic\.com|openai\.com|cursor\.com|cursor\.sh|aider\.chat|cognition\.ai)'
end='([^a-z0-9]|$)'
ai_re="^co-authored-by:[[:space:]]*${tools}${end}"
ai_re+="|^co-authored-by:.*<[^>]*@${domains}>"
ai_re+="|^co-authored-by:.*<[^>]*${tools}[^>]*@users\.noreply\.github\.com>"
ai_re+="|^claude-session:"
ai_re+="|^[^a-z0-9]*generated (with|by) \[?${tools}${end}"
ai_re+="|🤖"

bad=0
checked=0
for c in $commits; do
  checked=$((checked + 1))
  short="$(git rev-parse --short "$c")"
  subject="$(git log -1 --format=%s "$c")"
  parents="$(git log -1 --format=%p "$c" | wc -w)"
  if git log -1 --format=%B "$c" | grep -Eiq "$ai_re"; then
    printf '  %s AI attribution in message (DEV-4.3)\n' "$short"; bad=1
  fi
  if (( parents > 1 )); then
    continue   # merge commits: attribution only
  fi
  if ! [[ "$subject" =~ $subject_re ]] && [[ "$subject" != Revert\ \"* ]]; then
    printf '  %s subject not Conventional Commits (DEV-4.1): %s\n' "$short" "$subject"; bad=1
  fi
  author="$(git log -1 --format=%ae "$c")"
  if [[ "${GATE_CHECK_AUTHOR:-1}" == 1 && "$author" != "$email" ]]; then
    printf '  %s author %s, expected %s (DEV-4.2)\n' "$short" "$author" "$email"; bad=1
  fi
done

if (( bad != 0 )); then
  printf 'check-commits: failed\n' >&2
  exit 1
fi
printf '  %d commit(s) checked in %s\n' "$checked" "$range"
