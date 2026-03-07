# Author: Lean Tools MCP Contributors
# Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
# License: MIT

"""
File operation tools:
- lean_file_outline — document symbols / file skeleton
- lean_file_contents — read file with line numbers
- lean_declaration_file — find where a symbol is declared
- lean_local_search — fast local declaration search
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..lsp.pool import LSPPool


# ---------------------------------------------------------------------------
# lean_file_outline
# ---------------------------------------------------------------------------

def _format_symbol(sym: dict[str, Any], indent: int = 0) -> list[str]:
    """Recursively format a DocumentSymbol into readable lines."""
    kind_name = _symbol_kind_name(sym.get("kind", 0))
    name = sym.get("name", "?")
    detail = sym.get("detail", "")

    rng = sym.get("range", {})
    start_line = rng.get("start", {}).get("line", 0) + 1

    prefix = "  " * indent
    line = f"{prefix}{kind_name} {name}"
    if detail:
        line += f" : {detail}"
    line += f"  (line {start_line})"

    lines = [line]

    # Recurse into children
    for child in sym.get("children", []):
        lines.extend(_format_symbol(child, indent + 1))

    return lines


def _symbol_kind_name(kind: int) -> str:
    """Map LSP SymbolKind to a human-readable name."""
    names = {
        1: "file", 2: "module", 3: "namespace", 4: "package",
        5: "class", 6: "method", 7: "property", 8: "field",
        9: "constructor", 10: "enum", 11: "interface", 12: "function",
        13: "variable", 14: "constant", 15: "string", 16: "number",
        17: "boolean", 18: "array", 19: "object", 20: "key",
        21: "null", 22: "enum_member", 23: "struct", 24: "event",
        25: "operator", 26: "type_parameter",
    }
    return names.get(kind, f"kind_{kind}")


async def lean_file_outline(
    lsp_pool: LSPPool,
    file_path: str,
) -> str:
    """Get imports and declarations with type signatures. Token-efficient.

    Returns the file skeleton: imports, definitions, theorems, etc.
    with their type signatures and line numbers.

    Args:
        file_path: Absolute path to the .lean file

    Returns:
        Formatted outline of the file.
    """
    symbols = await lsp_pool.get_document_symbols(file_path)

    if not symbols:
        return "No symbols found in file (file may still be loading)."

    lines: list[str] = []
    for sym in symbols:
        lines.extend(_format_symbol(sym))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# lean_file_contents
# ---------------------------------------------------------------------------

async def lean_file_contents(
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Get file contents with optional line numbers.

    Args:
        file_path: Absolute path to the .lean file
        start_line: Start reading from this line (1-indexed, inclusive)
        end_line: Stop reading at this line (1-indexed, inclusive)

    Returns:
        File contents with line number annotations.
    """
    p = Path(file_path)
    if not p.exists():
        return f"File not found: {file_path}"

    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    all_lines = content.split("\n")

    # Apply line range filter (1-indexed)
    s = (start_line - 1) if start_line else 0
    e = end_line if end_line else len(all_lines)
    s = max(0, s)
    e = min(len(all_lines), e)

    selected = all_lines[s:e]

    # Format with line numbers
    width = len(str(e))
    annotated = []
    for i, line in enumerate(selected, start=s + 1):
        annotated.append(f"{i:>{width}}|{line}")

    return "\n".join(annotated)


# ---------------------------------------------------------------------------
# lean_declaration_file
# ---------------------------------------------------------------------------

async def lean_declaration_file(
    lsp_pool: LSPPool,
    file_path: str,
    symbol: str,
) -> str:
    """Get file where a symbol is declared. Symbol must be present in file first.

    Args:
        file_path: Absolute path to a .lean file that uses the symbol
        symbol: Symbol name (case sensitive, must be in file)

    Returns:
        Path and location of the symbol's declaration.
    """
    # Find the symbol in the file to get its position
    p = Path(file_path)
    if not p.exists():
        return f"File not found: {file_path}"

    content = p.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Search for the symbol in the file
    found_line = None
    found_col = None
    for i, line in enumerate(lines):
        # Find the symbol (as a whole word)
        match = re.search(r'\b' + re.escape(symbol) + r'\b', line)
        if match:
            found_line = i + 1  # 1-indexed
            found_col = match.start() + 1  # 1-indexed
            break

    if found_line is None:
        return f"Symbol '{symbol}' not found in file {file_path}"

    # Use goto-definition
    locations = await lsp_pool.get_definition(file_path, found_line, found_col)

    if not locations:
        return f"No definition found for '{symbol}'"

    results = []
    for loc in locations:
        uri = loc.get("uri", loc.get("targetUri", ""))
        rng = loc.get("range", loc.get("targetRange", {}))
        start = rng.get("start", {})
        line_num = start.get("line", 0) + 1

        # Convert URI to path
        if uri.startswith("file://"):
            from ..lsp.file_manager import uri_to_path
            decl_path = str(uri_to_path(uri))
        else:
            decl_path = uri

        results.append(f"{decl_path}:{line_num}")

    return "\n".join(results)


# ---------------------------------------------------------------------------
# lean_local_search
# ---------------------------------------------------------------------------

_DECL_LINE_RE = re.compile(
    r'^(?:private\s+)?(?:protected\s+)?(?:noncomputable\s+)?'
    r'(?:theorem|lemma|def|abbrev|instance|class|structure|inductive|axiom|opaque)\s+'
    r'(\S+)',
)
_NAMESPACE_RE = re.compile(r'^namespace\s+(\S+)')
_SECTION_RE = re.compile(r'^section\s+(\S+)')
_END_RE = re.compile(r'^end\s*(\S*)')


def _extract_declarations(content: str) -> list[tuple[str, int]]:
    """Extract (qualified_name, line_number) pairs from a .lean file.

    Tracks namespace/section/end blocks to build fully qualified names.
    Sections do NOT contribute to the qualified name prefix.
    """
    results: list[tuple[str, int]] = []

    # Each entry: ("namespace", name) or ("section", name)
    scope_stack: list[tuple[str, str]] = []

    for line_idx, raw_line in enumerate(content.split("\n")):
        line = raw_line.strip()

        # Skip comments
        if line.startswith("--"):
            continue

        # namespace Foo
        m = _NAMESPACE_RE.match(line)
        if m:
            scope_stack.append(("namespace", m.group(1)))
            continue

        # section Foo
        m = _SECTION_RE.match(line)
        if m:
            scope_stack.append(("section", m.group(1)))
            continue

        # end / end Foo
        m = _END_RE.match(line)
        if m and (m.group(0) != "end" or not line[3:].strip() or line == "end"):
            # Only process if it's a standalone 'end' or 'end <name>'
            end_name = m.group(1)
            if scope_stack:
                if end_name:
                    # Pop until we find the matching scope
                    for i in range(len(scope_stack) - 1, -1, -1):
                        if scope_stack[i][1] == end_name:
                            scope_stack.pop(i)
                            break
                else:
                    scope_stack.pop()
            continue

        # Declaration
        m = _DECL_LINE_RE.match(line)
        if m:
            short_name = m.group(1)
            ns_prefix = ".".join(
                name for kind, name in scope_stack if kind == "namespace"
            )
            qualified = f"{ns_prefix}.{short_name}" if ns_prefix else short_name
            results.append((qualified, line_idx + 1))

    return results


async def lean_local_search(
    file_path: str,
    query: str,
    limit: int = 10,
) -> str:
    """Fast local search to verify declarations exist. Use BEFORE trying a lemma name.

    Searches through .lean files in the project for declarations matching
    the query string. Returns fully qualified names (namespace-aware).

    Args:
        file_path: Absolute path to any .lean file in the project (used to
                   determine the project root)
        query: Declaration name, qualified name, or substring to search for
        limit: Maximum number of matches to return (default 10)

    Returns:
        Matching declarations found in the project.
    """
    p = Path(file_path).resolve()
    project_root = _find_project_root(p)

    if project_root is None:
        return f"Could not find project root (no lakefile.lean) for {file_path}"

    matches: list[str] = []
    query_lower = query.lower()

    search_dirs = [project_root]
    src_dir = project_root / "src"
    if src_dir.exists():
        search_dirs = [src_dir]
    lib_dir = project_root / "lib"
    if lib_dir.exists():
        search_dirs.append(lib_dir)

    for search_dir in search_dirs:
        if len(matches) >= limit:
            break
        for lean_file in search_dir.rglob("*.lean"):
            if len(matches) >= limit:
                break
            try:
                content = lean_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            decls = _extract_declarations(content)
            for qualified_name, line_num in decls:
                if query_lower in qualified_name.lower():
                    rel_path = lean_file.relative_to(project_root)
                    matches.append(f"{qualified_name}  ({rel_path}:{line_num})")
                    if len(matches) >= limit:
                        break

    if not matches:
        return f"No declarations matching '{query}' found in project."

    return f"Found {len(matches)} match(es):\n" + "\n".join(matches)


def _find_project_root(path: Path) -> Path | None:
    """Walk up from path to find the directory containing lakefile.lean."""
    current = path if path.is_dir() else path.parent
    for _ in range(20):  # Safety limit
        if (current / "lakefile.lean").exists():
            return current
        if (current / "lakefile.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None
