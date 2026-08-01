#!/usr/bin/env bash
# Check primitives for preflight.sh. Sourced, not executed.
#
# Every check prints one line and updates the pass/fail tally. Checks never
# abort the run; preflight reports everything wrong at once so a session gets
# the full picture in a single pass.

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0
FAILED_ITEMS=()

if [[ -t 1 ]]; then
  C_OK=$'\033[32m'; C_BAD=$'\033[31m'; C_WARN=$'\033[33m'
  C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_OK=""; C_BAD=""; C_WARN=""; C_DIM=""; C_BOLD=""; C_OFF=""
fi

: "${SSH_TIMEOUT:=5}"
: "${SSH_OPTS:=-o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT -o StrictHostKeyChecking=accept-new}"

section() { printf '\n%s%s%s\n' "$C_BOLD" "$1" "$C_OFF"; }

_pass() { PASS_COUNT=$((PASS_COUNT+1)); printf '  %sok  %s %-28s %s%s%s\n' "$C_OK" "$C_OFF" "$1" "$C_DIM" "${2:-}" "$C_OFF"; }
_fail() { FAIL_COUNT=$((FAIL_COUNT+1)); FAILED_ITEMS+=("$1${2:+ - $2}"); printf '  %sFAIL%s %-28s %s\n' "$C_BAD" "$C_OFF" "$1" "${2:-}"; }
_warn() { WARN_COUNT=$((WARN_COUNT+1)); printf '  %swarn%s %-28s %s\n' "$C_WARN" "$C_OFF" "$1" "${2:-}"; }

note() { printf '  %s%s%s\n' "$C_DIM" "$1" "$C_OFF"; }

# check_cmd <label> <command...>
# Fails if the command is not on PATH.
check_cmd() {
  local label="$1"; shift
  if command -v "$1" >/dev/null 2>&1; then
    _pass "$label" "$("$@" 2>&1 | head -n1)"
  else
    _fail "$label" "'$1' not found on PATH"
  fi
}

# check_tcp <label> <host> <port>
# Pure bash, no netcat dependency.
check_tcp() {
  local label="$1" host="$2" port="$3"
  if timeout "$SSH_TIMEOUT" bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null; then
    _pass "$label" "$host:$port open"
  else
    _fail "$label" "$host:$port unreachable"
  fi
}

# check_ssh <label> <user@host>
# Confirms key-based, non-interactive SSH actually works. This is the check
# that stops a fresh session from asking whether it has access.
check_ssh() {
  local label="$1" target="$2"
  local out
  if out=$(ssh $SSH_OPTS "$target" 'uptime' 2>&1); then
    _pass "$label" "$(echo "$out" | sed 's/^ *//')"
  else
    _fail "$label" "ssh $target failed: $(echo "$out" | head -n1)"
  fi
}

# check_http <label> <url> [expected_status]
check_http() {
  local label="$1" url="$2" want="${3:-200}"
  local code
  code=$(curl -fsS -o /dev/null -w '%{http_code}' --max-time "$SSH_TIMEOUT" "$url" 2>/dev/null) || code="000"
  if [[ "$code" == "$want" ]]; then
    _pass "$label" "$url -> $code"
  else
    _fail "$label" "$url -> $code (wanted $want)"
  fi
}

# check_container <label> <user@host> <container>
# Docker is the only supported deployment (there is no systemd path). Reports the
# container's health status, or its plain running state if it has no healthcheck.
check_container() {
  local label="$1" target="$2" name="$3" state
  state=$(ssh $SSH_OPTS "$target" "docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' '$name'" 2>/dev/null) || state="unreachable"
  if [[ "$state" == "healthy" || "$state" == "running" ]]; then
    _pass "$label" "$name $state"
  else
    _fail "$label" "$name is '$state'"
  fi
}

# check_file <label> <path>
check_file() {
  local label="$1" path="$2"
  if [[ -e "$path" ]]; then _pass "$label" "$path"; else _fail "$label" "missing: $path"; fi
}

# check_remote_file <label> <user@host> <path>
check_remote_file() {
  local label="$1" target="$2" path="$3"
  if ssh $SSH_OPTS "$target" "test -e '$path'" 2>/dev/null; then
    _pass "$label" "$target:$path"
  else
    _fail "$label" "missing on $target: $path"
  fi
}

# check_git  - branch, cleanliness, divergence from origin
check_git() {
  local branch dirty ahead behind
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || { _warn "git" "not a git repo"; return; }
  dirty=$(git status --porcelain | wc -l)
  _pass "git branch" "$branch @ $(git rev-parse --short HEAD)"
  if (( dirty > 0 )); then
    _warn "git worktree" "$dirty uncommitted change(s)"
  else
    _pass "git worktree" "clean"
  fi
  if git rev-parse --abbrev-ref "@{upstream}" >/dev/null 2>&1; then
    read -r behind ahead < <(git rev-list --left-right --count "@{upstream}...HEAD" 2>/dev/null)
    if (( ahead > 0 || behind > 0 )); then
      _warn "git upstream" "$ahead ahead, $behind behind"
    else
      _pass "git upstream" "in sync"
    fi
  fi
}

# check_disk <label> <path> <min_gb>
check_disk() {
  local label="$1" path="$2" min="$3" avail
  avail=$(df -BG --output=avail "$path" 2>/dev/null | tail -n1 | tr -dc '0-9')
  if [[ -z "$avail" ]]; then _fail "$label" "cannot stat $path"; return; fi
  if (( avail >= min )); then _pass "$label" "${avail}G free"; else _warn "$label" "${avail}G free, want >= ${min}G"; fi
}

summary() {
  printf '\n%s%d passed, %d failed, %d warnings%s\n' "$C_BOLD" "$PASS_COUNT" "$FAIL_COUNT" "$WARN_COUNT" "$C_OFF"
  if (( FAIL_COUNT > 0 )); then
    printf '%sBlocking failures:%s\n' "$C_BAD" "$C_OFF"
    printf '  - %s\n' "${FAILED_ITEMS[@]}"
    printf '\nDo not start work until these are resolved. If a check is wrong\n'
    printf 'rather than the environment, fix scripts/preflight.conf.\n'
    return 1
  fi
  return 0
}
# check_clock <label> <user@host> <max_offset_seconds>
check_clock() {
  local label="$1" target="$2" max="$3" out offset src
  out=$(ssh $SSH_OPTS "$target" 'chronyc tracking' 2>/dev/null) || { _fail "$label" "chronyc unreachable on $target"; return; }
  src=$(awk -F': ' '/Reference ID/ {print $2}' <<<"$out")
  offset=$(awk -F': ' '/Last offset/ {print $2}' <<<"$out" | awk '{print $1}')
  offset=${offset#[-+]}
  if awk "BEGIN{exit !($offset < $max)}"; then
    _pass "$label" "offset ${offset}s, ref $src"
  else
    _fail "$label" "offset ${offset}s exceeds ${max}s, ref $src"
  fi
}
# check_ntp_source <label> <user@host> <expected_source>
check_ntp_source() {
  local label="$1" target="$2" want="$3" out line
  out=$(ssh $SSH_OPTS "$target" 'chronyc sources' 2>/dev/null) || { _fail "$label" "chronyc unreachable on $target"; return; }
  line=$(grep -i -- "$want" <<<"$out") || { _fail "$label" "$want not in chrony sources"; return; }
  case "$line" in
    '^*'*) _pass "$label" "synced to $want" ;;
    '^+'*) _pass "$label" "$want present as fallback" ;;
    *)     _fail "$label" "$want present but not selected: $(awk '{print $1, $2}' <<<"$line")" ;;
  esac
}
