# Lean Project Manager Design

**Date:** 2026-03-16

**Scope:** Add `lean_build` and `lean_code_actions` using a small project-lifecycle layer rather than two isolated tool patches.

---

## Goal

Add two missing first-tier capabilities relative to `lean-lsp-mcp`:

- `lean_build`
- `lean_code_actions`

Do this in a way that also establishes a stable foundation for future project-level operations such as `lean_verify`, `execute-lean`, `execute-lean-persistent`, and `cleanup-session`.

---

## Why Scheme C

Scheme A would add the two tools directly and keep project operations scattered across `server.py`, tool modules, and the LSP pool. That is fast, but it does not give the codebase a single place to coordinate:

- `lake` subprocess execution
- environment preparation for patched Lean binaries
- LSP restart after successful builds
- serialization of project-mutating operations

Scheme C introduces a narrow project manager so those concerns live in one place.

This is the right trade-off here because:

- the repo already has a non-trivial runtime model (`LSPPool`, patched Lean discovery, in-process workers)
- `lean_build` should coordinate with that runtime, not bypass it
- the likely next tools are also project-lifecycle tools

---

## Current Context

The current server already has strong separation between:

- MCP registry and dispatch in `lean_tools_mcp/server.py`
- per-tool formatting wrappers in `lean_tools_mcp/tools/*.py`
- Lean JSON-RPC client in `lean_tools_mcp/lsp/client.py`
- pool orchestration in `lean_tools_mcp/lsp/pool.py`
- runtime config in `lean_tools_mcp/config.py`

This makes it feasible to add one more thin service layer without disturbing the existing architecture.

---

## Proposed Architecture

Introduce a new module:

- `lean_tools_mcp/project/manager.py`

with a primary class:

- `LeanProjectManager`

Responsibilities:

1. Own project-lifecycle operations.
2. Serialize build-like actions with an `asyncio.Lock`.
3. Run `lake` commands in the server's configured project root.
4. Ensure the command environment is compatible with the configured Lean binary.
5. Restart the `LSPPool` after successful builds.
6. Provide one project-level entrypoint for `lean_code_actions`, even if the initial implementation delegates most of the work to `LSPPool`.

Non-goals for this change:

- no generic task scheduler
- no long-lived persistent execution sessions yet
- no code-action application support yet
- no build caching/status database

---

## Component Breakdown

### 1. `LeanProjectManager`

Suggested fields:

- `project_root: Path`
- `lsp_pool: LSPPool`
- `lean_path: str`
- `build_timeout: float`
- `_build_lock: asyncio.Lock`

Suggested methods:

- `async build(...) -> BuildResult`
- `async code_actions(...) -> list[dict[str, Any]]`
- `_build_env() -> dict[str, str]`
- `_run_lake_command(args: list[str]) -> CommandResult`

### 2. `BuildResult`

A small dataclass describing:

- command sequence
- exit code
- stdout / stderr
- whether restart happened
- whether build succeeded

This keeps tool formatting separate from subprocess logic.

### 3. `lean_build` tool wrapper

New file:

- `lean_tools_mcp/tools/build.py`

Responsibilities:

- validate MCP arguments
- call `LeanProjectManager.build`
- format output into the repo's current text-first style

### 4. `lean_code_actions` tool wrapper

New file:

- `lean_tools_mcp/tools/code_actions.py`

Responsibilities:

- validate and normalize positions
- call `LeanProjectManager.code_actions`
- render both `CodeAction` and `Command` results in text form

### 5. LSP additions

Extend:

- `lean_tools_mcp/lsp/client.py`
- `lean_tools_mcp/lsp/pool.py`

with `get_code_actions(...)`.

No new protocol layer is needed because `JsonRpcTransport.send_request(...)` already exists.

---

## Data Flow

### `lean_code_actions`

1. MCP call reaches `server.py`.
2. Dispatcher routes to `tools/code_actions.py`.
3. Tool wrapper calls `LeanProjectManager.code_actions(...)`.
4. Manager delegates to `LSPPool.get_code_actions(...)`.
5. Pool picks one live client.
6. Client:
   - ensures file is open
   - waits for diagnostics on that same client
   - filters diagnostics intersecting the requested range
   - sends `textDocument/codeAction`
7. Tool wrapper formats the returned actions.

### `lean_build`

1. MCP call reaches `server.py`.
2. Dispatcher routes to `tools/build.py`.
3. Tool wrapper calls `LeanProjectManager.build(...)`.
4. Manager acquires `_build_lock`.
5. Manager optionally runs `lake clean`.
6. Manager runs `lake build [target]`.
7. If build succeeds, manager restarts `LSPPool`.
8. Tool wrapper formats a concise success/failure summary plus the requested tail of logs.

---

## API Shape

To stay project-consistent rather than clone `lean-lsp-mcp` exactly:

### `lean_code_actions`

Suggested MCP arguments:

- `file_path: string` required
- `line: integer` required
- `column: integer` required
- `end_line: integer` optional
- `end_column: integer` optional
- `max_actions: integer` optional, default `20`

Rationale:

- follows the existing positional style already used by `lean_goal`, `lean_hover_info`, `lean_state_search`
- avoids introducing LSP-native `range` objects into the public API

### `lean_build`

Suggested MCP arguments:

- `target: string` optional
- `clean: boolean` optional, default `false`
- `output_lines: integer` optional, default `80`

Rationale:

- the server already owns one project root, so no extra `project_root` argument is needed
- this mirrors the repo's current tool ergonomics

---

## Environment Handling

This is the main reason to use Scheme C instead of A.

`lean_build` must not blindly run `lake build` under whatever shell environment happens to exist. The manager should construct a build environment that is consistent with the configured Lean runtime:

- if `lean_path` is absolute and points to `.../bin/lean`, prepend its parent directory to `PATH`
- preserve current environment variables
- do not mutate global process environment

That keeps `lake` and `lean --server` aligned when the server is running against a patched Lean binary.

---

## Concurrency Rules

### Build lock

Only one build-like operation should run at a time.

The manager should enforce this with one lock:

- `lean_build` waits if another build is running
- future project-mutating tools can reuse the same lock

### LSP restart behavior

- restart only after a successful build
- do not restart after failed build
- restart the whole pool, not one client, to avoid stale mixed state

---

## Error Handling

### `lean_code_actions`

- file missing -> plain error string
- no actions -> clear “no code actions” result, not failure
- unsupported server method -> return actionable message

### `lean_build`

- `lake` not found -> explicit error
- timeout -> explicit timeout error
- build failure -> include last `output_lines` of stderr/stdout
- restart failure after successful build -> surface both facts:
  - build succeeded
  - LSP restart failed

---

## Testing Strategy

### Unit tests

Primary focus:

- server registry and schema
- manager build orchestration
- code-action formatting
- restart-on-success behavior

These should be mock-heavy and not require real Lean.

### Integration tests

Add only narrow integration coverage:

- `lean_code_actions` on a file with an obvious quick fix, if Lean environment supports it
- `lean_build` in a small temp project, if that can be done cheaply

If the integration fixture makes `lean_build` too expensive or flaky, keep it unit-tested first.

---

## Risks

### 1. Code action response shape varies

LSP may return a mix of:

- `CodeAction`
- `Command`

The formatter must handle both.

### 2. Diagnostics must come from the same client

If code actions depend on current diagnostics, the same client instance should gather diagnostics and send the request. This is why the method belongs in `LSPClient`, not just a tool wrapper.

### 3. Build environment mismatch

Using the wrong `lean` for `lake build` would produce confusing behavior. The manager must make the chosen runtime explicit.

---

## Recommendation

Implement Scheme C in a narrow way:

- one new `LeanProjectManager`
- one new `lean_build` tool
- one new `lean_code_actions` tool
- no broader service container refactor

That captures the long-term architectural benefit of Scheme C without over-expanding this change.
