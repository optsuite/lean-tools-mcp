#!/usr/bin/env bash
# Author: Zichen Wang
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

set -euo pipefail

usage() {
  cat <<'EOF'
One-click setup for Lean Tools MCP memory-optimized workflow.

This script can:
1) Build patched Lean (Phase 2) with default Lean 4.29 family.
2) Create/update a Lean project pinned to matching toolchain + Mathlib.
3) Install lean-tools-mcp into your current Python environment.
4) Sync the companion ask-math-oracle-mcp repository.
5) Write MCP config entries for Codex / Claude / Cursor.

Usage:
  bash memory_optimization/scripts/one_click_setup.sh [options]

Options:
  --lean-version <ver>       Lean version input (default: v4.29.0)
                             Note: v4.29.0 maps to build tag v4.29.0-rc2.
  --mathlib-rev <rev>        Mathlib git revision/tag (default: v4.29.0-rc2)
  --project-root <path>      Lean project root (default: ~/lean-mcp-v429)
  --lean-builds-dir <path>   Patched lean install dir (default: ~/lean-builds)
  --lean-path <path>         Use an existing patched lean binary directly
  --python <bin>             Python executable (default: python3)
  --jobs <n>                 Parallel build jobs (default: CPU cores)
  --server-name <name>       MCP server key in client config (default: lean-tools-mcp)
  --ask-math-oracle-repo <u> Repo URL/path for companion MCP
                             (default: https://github.com/imathwy/ask-math-oracle-mcp.git)
  --ask-math-oracle-dir <p>  Install directory for companion MCP
                             (default: ~/.codex/vendor/ask-math-oracle-mcp)

  --no-build-lean            Skip patched lean build step
  --no-install-python        Skip pip install -e ".[sse,dev]"
  --no-mathlib-setup         Skip lake update / lake exe cache get
  --no-install-ask-math-oracle
                             Skip syncing and registering companion MCP
  --no-install-codex         Do not write ~/.codex/config.toml
  --no-install-claude        Do not write Claude Desktop config
  --install-cursor           Also write <project>/.cursor/mcp.json

  -h, --help                 Show this help
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: command not found: $cmd" >&2
    exit 1
  fi
}

cpu_jobs_default() {
  if command -v getconf >/dev/null 2>&1; then
    getconf _NPROCESSORS_ONLN 2>/dev/null || echo 8
  else
    echo 8
  fi
}

normalize_lean_tag() {
  local v="$1"
  if [[ "$v" != v* ]]; then
    v="v$v"
  fi
  echo "$v"
}

LEAN_VERSION_INPUT="v4.29.0"
MATHLIB_REV="v4.29.0-rc2"
PROJECT_ROOT="$HOME/lean-mcp-v429"
LEAN_BUILDS_DIR="$HOME/lean-builds"
LEAN_BIN_OVERRIDE=""
PYTHON_BIN="python3"
JOBS="$(cpu_jobs_default)"
SERVER_NAME="lean-tools-mcp"
ASK_MATH_ORACLE_REPO_URL="https://github.com/imathwy/ask-math-oracle-mcp.git"
ASK_MATH_ORACLE_DIR="$HOME/.codex/vendor/ask-math-oracle-mcp"
ASK_MATH_ORACLE_SERVER_NAME="ask-math-oracle"
ASK_MATH_ORACLE_STARTUP_TIMEOUT_SEC="60"

DO_BUILD_LEAN=1
DO_INSTALL_PYTHON=1
DO_MATHLIB_SETUP=1
DO_INSTALL_ASK_MATH_ORACLE=1
DO_INSTALL_CODEX=1
DO_INSTALL_CLAUDE=1
DO_INSTALL_CURSOR=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lean-version)
      LEAN_VERSION_INPUT="$2"
      shift 2
      ;;
    --mathlib-rev)
      MATHLIB_REV="$2"
      shift 2
      ;;
    --project-root)
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --lean-builds-dir)
      LEAN_BUILDS_DIR="$2"
      shift 2
      ;;
    --lean-path)
      LEAN_BIN_OVERRIDE="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --jobs)
      JOBS="$2"
      shift 2
      ;;
    --server-name)
      SERVER_NAME="$2"
      shift 2
      ;;
    --ask-math-oracle-repo)
      ASK_MATH_ORACLE_REPO_URL="$2"
      shift 2
      ;;
    --ask-math-oracle-dir)
      ASK_MATH_ORACLE_DIR="$2"
      shift 2
      ;;
    --no-build-lean)
      DO_BUILD_LEAN=0
      shift
      ;;
    --no-install-python)
      DO_INSTALL_PYTHON=0
      shift
      ;;
    --no-mathlib-setup)
      DO_MATHLIB_SETUP=0
      shift
      ;;
    --no-install-ask-math-oracle)
      DO_INSTALL_ASK_MATH_ORACLE=0
      shift
      ;;
    --no-install-codex)
      DO_INSTALL_CODEX=0
      shift
      ;;
    --no-install-claude)
      DO_INSTALL_CLAUDE=0
      shift
      ;;
    --install-cursor)
      DO_INSTALL_CURSOR=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMORY_OPT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$MEMORY_OPT_ROOT/.." && pwd)"

LEAN_VERSION_TAG="$(normalize_lean_tag "$LEAN_VERSION_INPUT")"
LEAN_VERSION_NOTE="$LEAN_VERSION_TAG"
if [[ "$LEAN_VERSION_TAG" == "v4.29.0" ]]; then
  LEAN_VERSION_TAG="v4.29.0-rc2"
  LEAN_VERSION_NOTE="v4.29.0 (mapped to tag $LEAN_VERSION_TAG)"
fi

PROJECT_ROOT="${PROJECT_ROOT/#\~/$HOME}"
LEAN_BUILDS_DIR="${LEAN_BUILDS_DIR/#\~/$HOME}"
ASK_MATH_ORACLE_DIR="${ASK_MATH_ORACLE_DIR/#\~/$HOME}"
LEAN_BIN="$LEAN_BUILDS_DIR/$LEAN_VERSION_TAG/bin/lean"
if [[ -n "$LEAN_BIN_OVERRIDE" ]]; then
  LEAN_BIN="${LEAN_BIN_OVERRIDE/#\~/$HOME}"
  if [[ "$DO_BUILD_LEAN" -eq 1 ]]; then
    DO_BUILD_LEAN=0
  fi
fi

echo "== Lean Tools MCP one-click setup =="
echo "Lean version input:    $LEAN_VERSION_INPUT"
echo "Lean build tag:        $LEAN_VERSION_NOTE"
echo "Mathlib revision:      $MATHLIB_REV"
echo "Project root:          $PROJECT_ROOT"
echo "Lean builds dir:       $LEAN_BUILDS_DIR"
echo "Lean binary target:    $LEAN_BIN"
echo "Python:                $PYTHON_BIN"
echo "Ask-math-oracle repo:  $ASK_MATH_ORACLE_REPO_URL"
echo "Ask-math-oracle dir:   $ASK_MATH_ORACLE_DIR"
echo

require_cmd "$PYTHON_BIN"
require_cmd git
require_cmd lake

mkdir -p "$LEAN_BUILDS_DIR"
mkdir -p "$PROJECT_ROOT"

if [[ "$DO_BUILD_LEAN" -eq 1 ]]; then
  echo "[1/7] Building patched Lean..."
  "$PYTHON_BIN" "$MEMORY_OPT_ROOT/scripts/build_lean.py" \
    --version "$LEAN_VERSION_TAG" \
    --output "$LEAN_BUILDS_DIR" \
    --jobs "$JOBS"
else
  echo "[1/7] Skipped patched Lean build (--no-build-lean)."
fi

if [[ ! -x "$LEAN_BIN" ]]; then
  echo "Error: patched Lean binary not found: $LEAN_BIN" >&2
  exit 1
fi

echo
echo "[2/7] Verifying patched Lean binary..."
"$LEAN_BIN" --version

echo
echo "[3/7] Preparing Lean project with Mathlib..."
TOOLCHAIN_FILE="$PROJECT_ROOT/lean-toolchain"
LAKEFILE="$PROJECT_ROOT/lakefile.lean"
MAIN_FILE="$PROJECT_ROOT/Main.lean"

if [[ ! -f "$TOOLCHAIN_FILE" ]]; then
  printf "leanprover/lean4:%s\n" "$LEAN_VERSION_TAG" > "$TOOLCHAIN_FILE"
  echo "  Wrote $TOOLCHAIN_FILE"
else
  echo "  Keeping existing $TOOLCHAIN_FILE"
fi

if [[ ! -f "$LAKEFILE" ]]; then
  cat > "$LAKEFILE" <<EOF
import Lake
open Lake DSL

package «lean_mcp_v429» where

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "$MATHLIB_REV"

@[default_target]
lean_lib «LeanMcpV429» where
  srcDir := "."
EOF
  echo "  Wrote $LAKEFILE"
else
  echo "  Keeping existing $LAKEFILE"
fi

if [[ ! -f "$MAIN_FILE" ]]; then
  cat > "$MAIN_FILE" <<'EOF'
import Mathlib.Tactic

theorem demo_add : 1 + 1 = 2 := by
  omega
EOF
  echo "  Wrote $MAIN_FILE"
fi

if [[ "$DO_MATHLIB_SETUP" -eq 1 ]]; then
  (
    cd "$PROJECT_ROOT"
    echo "  Running lake update..."
    lake update
    echo "  Running lake exe cache get..."
    lake exe cache get
  )
else
  echo "  Skipped mathlib setup (--no-mathlib-setup)."
fi

if [[ "$DO_INSTALL_PYTHON" -eq 1 ]]; then
  echo
  echo "[4/7] Installing lean-tools-mcp Python package..."
  (
    cd "$REPO_ROOT"
    "$PYTHON_BIN" -m pip install -e ".[sse,dev]"
  )
else
  echo
  echo "[4/7] Skipped Python install (--no-install-python)."
fi

if [[ "$DO_INSTALL_ASK_MATH_ORACLE" -eq 1 ]]; then
  echo
  echo "[5/7] Syncing ask-math-oracle-mcp companion server..."
  mkdir -p "$(dirname "$ASK_MATH_ORACLE_DIR")"
  if [[ -d "$ASK_MATH_ORACLE_DIR/.git" ]]; then
    (
      cd "$ASK_MATH_ORACLE_DIR"
      git pull --ff-only
    )
  elif [[ -f "$ASK_MATH_ORACLE_DIR/ask_math_oracle_mcp/server.py" ]]; then
    echo "  Keeping existing companion install: $ASK_MATH_ORACLE_DIR"
  else
    git clone --depth 1 "$ASK_MATH_ORACLE_REPO_URL" "$ASK_MATH_ORACLE_DIR"
  fi
else
  echo
  echo "[5/7] Skipped companion MCP install (--no-install-ask-math-oracle)."
fi

MCP_COMMAND="$(command -v lean-tools-mcp || true)"
COMMON_ARGS=("--project-root" "$PROJECT_ROOT" "--inprocess" "--lean-path" "$LEAN_BIN")
if [[ -n "$MCP_COMMAND" ]]; then
  MCP_ARGS=("${COMMON_ARGS[@]}")
else
  MCP_COMMAND="$PYTHON_BIN"
  MCP_ARGS=("-m" "lean_tools_mcp.server" "${COMMON_ARGS[@]}")
fi

ASK_MATH_ORACLE_COMMAND="$PYTHON_BIN"
ASK_MATH_ORACLE_ARGS=("$ASK_MATH_ORACLE_DIR/ask_math_oracle_mcp/server.py")
ASK_MATH_ORACLE_ENV_KEYS=()
if [[ -n "${ASK_MATH_ORACLE_OPENAI_API_KEY:-${OPENAI_API_KEY:-}}" ]]; then
  ASK_MATH_ORACLE_ENV_KEYS+=("ASK_MATH_ORACLE_OPENAI_API_KEY=${ASK_MATH_ORACLE_OPENAI_API_KEY:-${OPENAI_API_KEY:-}}")
fi
if [[ -n "${ASK_MATH_ORACLE_ANTHROPIC_API_KEY:-${ANTHROPIC_API_KEY:-}}" ]]; then
  ASK_MATH_ORACLE_ENV_KEYS+=("ASK_MATH_ORACLE_ANTHROPIC_API_KEY=${ASK_MATH_ORACLE_ANTHROPIC_API_KEY:-${ANTHROPIC_API_KEY:-}}")
fi
if [[ -n "${ASK_MATH_ORACLE_GOOGLE_API_KEY:-${GOOGLE_API_KEY:-}}" ]]; then
  ASK_MATH_ORACLE_ENV_KEYS+=("ASK_MATH_ORACLE_GOOGLE_API_KEY=${ASK_MATH_ORACLE_GOOGLE_API_KEY:-${GOOGLE_API_KEY:-}}")
fi
if [[ -n "${ASK_MATH_ORACLE_OPENAI_BASE_URL:-${OPENAI_BASE_URL:-}}" ]]; then
  ASK_MATH_ORACLE_ENV_KEYS+=("ASK_MATH_ORACLE_OPENAI_BASE_URL=${ASK_MATH_ORACLE_OPENAI_BASE_URL:-${OPENAI_BASE_URL:-}}")
fi
if [[ -n "${ASK_MATH_ORACLE_OPENAI_MODEL:-}" ]]; then
  ASK_MATH_ORACLE_ENV_KEYS+=("ASK_MATH_ORACLE_OPENAI_MODEL=${ASK_MATH_ORACLE_OPENAI_MODEL}")
fi
if [[ -n "${ASK_MATH_ORACLE_ANTHROPIC_BASE_URL:-}" ]]; then
  ASK_MATH_ORACLE_ENV_KEYS+=("ASK_MATH_ORACLE_ANTHROPIC_BASE_URL=${ASK_MATH_ORACLE_ANTHROPIC_BASE_URL}")
fi
if [[ -n "${ASK_MATH_ORACLE_ANTHROPIC_MODEL:-}" ]]; then
  ASK_MATH_ORACLE_ENV_KEYS+=("ASK_MATH_ORACLE_ANTHROPIC_MODEL=${ASK_MATH_ORACLE_ANTHROPIC_MODEL}")
fi
if [[ -n "${ASK_MATH_ORACLE_ANTHROPIC_VERSION:-${ANTHROPIC_VERSION:-}}" ]]; then
  ASK_MATH_ORACLE_ENV_KEYS+=("ASK_MATH_ORACLE_ANTHROPIC_VERSION=${ASK_MATH_ORACLE_ANTHROPIC_VERSION:-${ANTHROPIC_VERSION:-}}")
fi
if [[ -n "${ASK_MATH_ORACLE_GEMINI_MODEL:-}" ]]; then
  ASK_MATH_ORACLE_ENV_KEYS+=("ASK_MATH_ORACLE_GEMINI_MODEL=${ASK_MATH_ORACLE_GEMINI_MODEL}")
fi
if [[ -n "${ASK_MATH_ORACLE_TIMEOUT_SEC:-}" ]]; then
  ASK_MATH_ORACLE_ENV_KEYS+=("ASK_MATH_ORACLE_TIMEOUT_SEC=${ASK_MATH_ORACLE_TIMEOUT_SEC}")
fi
if [[ -n "${ASK_MATH_ORACLE_REASONING_EFFORT:-}" ]]; then
  ASK_MATH_ORACLE_ENV_KEYS+=("ASK_MATH_ORACLE_REASONING_EFFORT=${ASK_MATH_ORACLE_REASONING_EFFORT}")
fi
if [[ -n "${ASK_MATH_ORACLE_DEBUG_MCP:-}" ]]; then
  ASK_MATH_ORACLE_ENV_KEYS+=("ASK_MATH_ORACLE_DEBUG_MCP=${ASK_MATH_ORACLE_DEBUG_MCP}")
fi

update_json_mcp_config() {
  local cfg_path="$1"
  local server_name="$2"
  local command="$3"
  local args_count="$4"
  shift 4
  local -a args=("${@:1:$args_count}")
  shift "$args_count"
  local -a env_kv=("$@")
  local -a python_args=("$cfg_path" "$server_name" "$command" "$args_count" "${args[@]}")
  if (( ${#env_kv[@]} > 0 )); then
    python_args+=(-- "${env_kv[@]}")
  fi
  "$PYTHON_BIN" - "${python_args[@]}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
server_name = sys.argv[2]
command = sys.argv[3]
args_count = int(sys.argv[4])
args = sys.argv[5:5 + args_count]
rest = sys.argv[5 + args_count:]
if rest and rest[0] == '--':
    rest = rest[1:]
env = {}
for item in rest:
    if '=' not in item:
        continue
    key, value = item.split('=', 1)
    env[key] = value

if path.exists():
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
else:
    data = {}

mcp = data.get('mcpServers')
if not isinstance(mcp, dict):
    mcp = {}
data['mcpServers'] = mcp
entry = {
    'command': command,
    'args': args,
}
if env:
    entry['env'] = env
mcp[server_name] = entry

path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(path)
PY
}

upsert_codex_toml_block() {
  local cfg_path="$1"
  local start_marker="$2"
  local end_marker="$3"
  local server_name="$4"
  local command="$5"
  local startup_timeout="$6"
  local args_count="$7"
  shift 7
  local -a args=("${@:1:$args_count}")
  shift "$args_count"
  local -a env_kv=("$@")
  local -a python_args=("$server_name" "$command" "$startup_timeout" "$args_count" "${args[@]}")
  local tmp_block
  tmp_block="$(mktemp)"
  if (( ${#env_kv[@]} > 0 )); then
    python_args+=(-- "${env_kv[@]}")
  fi

  "$PYTHON_BIN" - "${python_args[@]}" > "$tmp_block" <<'PY'
import sys

server_name = sys.argv[1]
command = sys.argv[2]
startup_timeout = sys.argv[3]
args_count = int(sys.argv[4])
args = sys.argv[5:5 + args_count]
rest = sys.argv[5 + args_count:]
if rest and rest[0] == '--':
    rest = rest[1:]
env = []
for item in rest:
    if '=' not in item:
        continue
    key, value = item.split('=', 1)
    env.append((key, value))

def q(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

print(f"[mcp_servers.{server_name}]")
print(f"command = {q(command)}")
print("args = [" + ", ".join(q(a) for a in args) + "]")
if startup_timeout and startup_timeout != '0':
    print(f"startup_timeout_sec = {startup_timeout}")
if env:
    print("env = { " + ", ".join(f"{key} = {q(value)}" for key, value in env) + " }")
PY

  "$PYTHON_BIN" - "$cfg_path" "$start_marker" "$end_marker" "$tmp_block" <<'PY'
import sys
from pathlib import Path

cfg_path = Path(sys.argv[1]).expanduser()
start = sys.argv[2]
end = sys.argv[3]
block_file = Path(sys.argv[4])

block = block_file.read_text(encoding='utf-8').rstrip() + '\n'
wrapped = f"{start}\n{block}{end}\n"

if cfg_path.exists():
    text = cfg_path.read_text(encoding='utf-8')
else:
    text = ''

if start in text and end in text:
    prefix = text.split(start, 1)[0]
    suffix = text.split(end, 1)[1]
    if suffix.startswith('\n'):
        suffix = suffix[1:]
    new_text = prefix.rstrip() + '\n\n' + wrapped + ('\n' + suffix if suffix else '')
else:
    sep = '\n' if (text and not text.endswith('\n')) else ''
    new_text = text + sep + ('\n' if text.strip() else '') + wrapped

cfg_path.parent.mkdir(parents=True, exist_ok=True)
cfg_path.write_text(new_text, encoding='utf-8')
print(cfg_path)
PY

  rm -f "$tmp_block"
}
echo
echo "[6/7] Writing MCP client configurations..."
if [[ "$DO_INSTALL_CODEX" -eq 1 ]]; then
  CODEX_CFG="$HOME/.codex/config.toml"
  echo "  Updating Codex config: $CODEX_CFG"
  upsert_codex_toml_block "$CODEX_CFG" "# >>> lean-tools-mcp one-click >>>" "# <<< lean-tools-mcp one-click <<<" "$SERVER_NAME" "$MCP_COMMAND" "0" "${#MCP_ARGS[@]}" "${MCP_ARGS[@]}"
  if [[ "$DO_INSTALL_ASK_MATH_ORACLE" -eq 1 ]]; then
    if (( ${#ASK_MATH_ORACLE_ENV_KEYS[@]} > 0 )); then
      upsert_codex_toml_block "$CODEX_CFG" "# >>> ask-math-oracle one-click >>>" "# <<< ask-math-oracle one-click <<<" "$ASK_MATH_ORACLE_SERVER_NAME" "$ASK_MATH_ORACLE_COMMAND" "$ASK_MATH_ORACLE_STARTUP_TIMEOUT_SEC" "${#ASK_MATH_ORACLE_ARGS[@]}" "${ASK_MATH_ORACLE_ARGS[@]}" "${ASK_MATH_ORACLE_ENV_KEYS[@]}"
    else
      upsert_codex_toml_block "$CODEX_CFG" "# >>> ask-math-oracle one-click >>>" "# <<< ask-math-oracle one-click <<<" "$ASK_MATH_ORACLE_SERVER_NAME" "$ASK_MATH_ORACLE_COMMAND" "$ASK_MATH_ORACLE_STARTUP_TIMEOUT_SEC" "${#ASK_MATH_ORACLE_ARGS[@]}" "${ASK_MATH_ORACLE_ARGS[@]}"
    fi
  fi
else
  echo "  Skipped Codex config (--no-install-codex)."
fi

if [[ "$DO_INSTALL_CLAUDE" -eq 1 ]]; then
  CLAUDE_CFG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
  echo "  Updating Claude config: $CLAUDE_CFG"
  update_json_mcp_config "$CLAUDE_CFG" "$SERVER_NAME" "$MCP_COMMAND" "${#MCP_ARGS[@]}" "${MCP_ARGS[@]}"
  if [[ "$DO_INSTALL_ASK_MATH_ORACLE" -eq 1 ]]; then
    if (( ${#ASK_MATH_ORACLE_ENV_KEYS[@]} > 0 )); then
      update_json_mcp_config "$CLAUDE_CFG" "$ASK_MATH_ORACLE_SERVER_NAME" "$ASK_MATH_ORACLE_COMMAND" "${#ASK_MATH_ORACLE_ARGS[@]}" "${ASK_MATH_ORACLE_ARGS[@]}" "${ASK_MATH_ORACLE_ENV_KEYS[@]}"
    else
      update_json_mcp_config "$CLAUDE_CFG" "$ASK_MATH_ORACLE_SERVER_NAME" "$ASK_MATH_ORACLE_COMMAND" "${#ASK_MATH_ORACLE_ARGS[@]}" "${ASK_MATH_ORACLE_ARGS[@]}"
    fi
  fi
else
  echo "  Skipped Claude config (--no-install-claude)."
fi

if [[ "$DO_INSTALL_CURSOR" -eq 1 ]]; then
  CURSOR_CFG="$PROJECT_ROOT/.cursor/mcp.json"
  echo "  Updating Cursor config: $CURSOR_CFG"
  update_json_mcp_config "$CURSOR_CFG" "$SERVER_NAME" "$MCP_COMMAND" "${#MCP_ARGS[@]}" "${MCP_ARGS[@]}"
  if [[ "$DO_INSTALL_ASK_MATH_ORACLE" -eq 1 ]]; then
    if (( ${#ASK_MATH_ORACLE_ENV_KEYS[@]} > 0 )); then
      update_json_mcp_config "$CURSOR_CFG" "$ASK_MATH_ORACLE_SERVER_NAME" "$ASK_MATH_ORACLE_COMMAND" "${#ASK_MATH_ORACLE_ARGS[@]}" "${ASK_MATH_ORACLE_ARGS[@]}" "${ASK_MATH_ORACLE_ENV_KEYS[@]}"
    else
      update_json_mcp_config "$CURSOR_CFG" "$ASK_MATH_ORACLE_SERVER_NAME" "$ASK_MATH_ORACLE_COMMAND" "${#ASK_MATH_ORACLE_ARGS[@]}" "${ASK_MATH_ORACLE_ARGS[@]}"
    fi
  fi
else
  echo "  Skipped Cursor config (use --install-cursor to enable)."
fi

echo
echo "[7/7] Done."
echo
echo "Patched Lean binary:"
echo "  $LEAN_BIN"
echo
echo "Lean project root:"
echo "  $PROJECT_ROOT"
echo
if [[ "$DO_INSTALL_ASK_MATH_ORACLE" -eq 1 ]]; then
  echo "Ask-math-oracle companion root:"
  echo "  $ASK_MATH_ORACLE_DIR"
  echo
fi
echo "Run manually:"
echo "  lean-tools-mcp --project-root \"$PROJECT_ROOT\" --inprocess --lean-path \"$LEAN_BIN\""
echo
if [[ "$DO_INSTALL_ASK_MATH_ORACLE" -eq 1 ]]; then
  echo "Companion MCP entry written as:"
  echo "  $ASK_MATH_ORACLE_SERVER_NAME"
  echo
fi
echo "If lean-tools-mcp command is unavailable in PATH, use:"
echo "  $PYTHON_BIN -m lean_tools_mcp.server --project-root \"$PROJECT_ROOT\" --inprocess --lean-path \"$LEAN_BIN\""
