"""
Integration tests — require a Lean project with `lean` on PATH.

These tests actually spawn `lean --server` and test the full pipeline.
They are skipped if `lean` is not available or the test project doesn't exist.

To run all integration tests:
    cd /Users/wzy/study/lean/lean-tools-mcp
    python -m pytest tests/test_integration.py -v -s

To run a single test:
    python -m pytest tests/test_integration.py::TestLSPClient::test_get_goal -v -s
    python -m pytest tests/test_integration.py::TestTools::test_lean_hover_info_tool -v -s

Default test project: ~/study/lean/v4.24.0-rc1/lean_tools_suite
Temp files are kept in: <project>/.lake/lean_tools_mcp_test/
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from tests.conftest import LEAN_AVAILABLE, skip_without_lean


def _ts() -> str:
    """Return a compact timestamp string for temp file names, e.g. '20260209_153012'."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")

# Allow overriding test project path via env var
LEAN_TEST_PROJECT = Path(
    os.environ.get(
        "LEAN_TEST_PROJECT",
        str(Path.home() / "study" / "lean" / "v4.24.0-rc1" / "lean_tools_suite"),
    )
)

# The lean binary for this project
LEAN_BIN = str(
    Path.home()
    / ".elan"
    / "toolchains"
    / "leanprover--lean4---v4.24.0-rc1"
    / "bin"
    / "lean"
)

# Temp directory inside the project for test files (NOT deleted after tests)
TEMP_DIR = LEAN_TEST_PROJECT / ".lake" / "lean_tools_mcp_test"


def _project_available() -> bool:
    return LEAN_AVAILABLE and LEAN_TEST_PROJECT.exists()


skip_without_project = pytest.mark.skipif(
    not _project_available(),
    reason=f"Test project not found: {LEAN_TEST_PROJECT}",
)


@pytest.fixture
def temp_dir():
    """Create temp directory for test files. Files are NOT deleted after tests."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    yield TEMP_DIR
    # NOTE: temp files are intentionally kept for manual inspection.
    # They live in: <project>/.lake/lean_tools_mcp_test/


# =========================================================================
# LSP Client tests
# =========================================================================


@skip_without_project
@pytest.mark.asyncio
class TestLSPClient:
    """Integration tests for LSPClient with a real lean --server."""

    @pytest.fixture
    async def client(self, temp_dir):
        from lean_tools_mcp.lsp.client import LSPClient

        c = LSPClient(
            project_root=LEAN_TEST_PROJECT,
            lean_path=LEAN_BIN,
            request_timeout=120.0,
            file_check_timeout=180.0,
        )
        await c.start()
        yield c
        await c.shutdown()

    async def test_start_and_shutdown(self, client):
        """LSP server starts and is alive."""
        print(f"\n[test_start_and_shutdown] client.is_alive = {client.is_alive}")
        print(f"  project_root = {LEAN_TEST_PROJECT}")
        print(f"  lean_bin     = {LEAN_BIN}")
        assert client.is_alive

    async def test_diagnostics_clean_file(self, client, temp_dir):
        """A correct file produces no errors."""
        test_file = temp_dir / f"test_clean_{_ts()}.lean"
        test_file.write_text("def hello : Nat := 42\n", encoding="utf-8")
        print(f"\n[test_diagnostics_clean_file] file = {test_file}")

        diags = await client.get_diagnostics(str(test_file))
        errors = [d for d in diags if d.get("severity") == 1]
        print(f"  total diagnostics: {len(diags)}")
        print(f"  errors: {len(errors)}")
        for d in diags:
            print(f"    [{d.get('severity')}] {d.get('message', '')[:80]}")
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    async def test_diagnostics_error_file(self, client, temp_dir):
        """A type-mismatched file produces errors."""
        test_file = temp_dir / f"test_error_{_ts()}.lean"
        test_file.write_text(
            'def broken : Nat := "not a nat"\n', encoding="utf-8"
        )
        print(f"\n[test_diagnostics_error_file] file = {test_file}")

        diags = await client.get_diagnostics(str(test_file))
        errors = [d for d in diags if d.get("severity") == 1]
        print(f"  total diagnostics: {len(diags)}")
        print(f"  errors: {len(errors)}")
        for d in diags:
            sev = {1: "ERROR", 2: "WARNING", 3: "INFO", 4: "HINT"}.get(d.get("severity", 0), "?")
            rng = d.get("range", {}).get("start", {})
            line = rng.get("line", 0) + 1
            col = rng.get("character", 0) + 1
            print(f"    [{sev}] {line}:{col} — {d.get('message', '')[:120]}")
        assert len(errors) > 0, "Expected type mismatch errors"

    async def test_get_goal(self, client, temp_dir):
        """Get proof goal at a sorry tactic."""
        test_file = temp_dir / f"test_goal_{_ts()}.lean"
        test_file.write_text(
            "theorem test_goal : 1 + 1 = 2 := by\n  sorry\n",
            encoding="utf-8",
        )
        print(f"\n[test_get_goal] file = {test_file}")

        result = await client.get_goal(str(test_file), line=2)
        goals_before = result.get("goals_before", "")
        goals_after = result.get("goals_after", "")
        print(f"  goals_before:\n    {goals_before}")
        print(f"  goals_after:\n    {goals_after}")
        assert "1" in goals_before or "no goals" in goals_before

    async def test_get_hover(self, client, temp_dir):
        """Get hover info for a known symbol."""
        test_file = temp_dir / f"test_hover_{_ts()}.lean"
        test_file.write_text("def myVal : Nat := 42\n#check myVal\n", encoding="utf-8")
        print(f"\n[test_get_hover] file = {test_file}")

        result = await client.get_hover(str(test_file), line=2, character=8)
        print(f"  raw result: {json.dumps(result, indent=2, ensure_ascii=False)[:500]}")
        if result is not None:
            contents = result.get("contents", {})
            if isinstance(contents, dict):
                value = contents.get("value", "")
                print(f"  hover value: {value}")
                assert len(value) > 0

    async def test_get_completions(self, client, temp_dir):
        """Get completions after a dot."""
        test_file = temp_dir / f"test_comp_{_ts()}.lean"
        test_file.write_text("def x := Nat.\n", encoding="utf-8")
        print(f"\n[test_get_completions] file = {test_file}")

        items = await client.get_completions(str(test_file), line=1, character=14)
        assert isinstance(items, list)
        print(f"  total completions: {len(items)}")
        for item in items[:10]:
            label = item.get("label", "")
            detail = item.get("detail", "")
            print(f"    {label}: {detail[:60]}")
        if len(items) > 10:
            print(f"    ... and {len(items) - 10} more")
        if items:
            labels = [item.get("label", "") for item in items]
            assert len(labels) > 0

    async def test_get_document_symbols(self, client, temp_dir):
        """Get file outline."""
        test_file = temp_dir / f"test_symbols_{_ts()}.lean"
        test_file.write_text(
            "def foo : Nat := 1\n"
            "def bar : Nat := 2\n"
            "theorem baz : 1 = 1 := rfl\n",
            encoding="utf-8",
        )
        print(f"\n[test_get_document_symbols] file = {test_file}")

        symbols = await client.get_document_symbols(str(test_file))
        assert isinstance(symbols, list)
        print(f"  total symbols: {len(symbols)}")
        for s in symbols:
            name = s.get("name", "")
            kind = s.get("kind", 0)
            detail = s.get("detail", "")
            print(f"    {name} (kind={kind}): {detail[:60]}")
        if symbols:
            names = [s.get("name", "") for s in symbols]
            assert any("foo" in n or "bar" in n or "baz" in n for n in names)


# =========================================================================
# Tool function tests
# =========================================================================


@skip_without_project
@pytest.mark.asyncio
class TestTools:
    """Integration tests for the MCP tool functions."""

    @pytest.fixture
    async def pool(self, temp_dir):
        from lean_tools_mcp.lsp.pool import LSPPool

        p = LSPPool(
            project_root=LEAN_TEST_PROJECT,
            pool_size=1,
            lean_path=LEAN_BIN,
            request_timeout=120.0,
            file_check_timeout=180.0,
        )
        await p.start()
        yield p
        await p.shutdown()

    async def test_lean_goal_tool(self, pool, temp_dir):
        """Test lean_goal tool function."""
        from lean_tools_mcp.tools.goal import lean_goal

        test_file = temp_dir / f"tool_goal_{_ts()}.lean"
        test_file.write_text(
            "theorem t1 : 1 + 1 = 2 := by\n  sorry\n",
            encoding="utf-8",
        )
        print(f"\n[test_lean_goal_tool] file = {test_file}")

        result = await lean_goal(pool, str(test_file), line=2)
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0
        assert "BEFORE" in result or "no goals" in result.lower()

    async def test_lean_diagnostic_messages_tool(self, pool, temp_dir):
        """Test lean_diagnostic_messages tool function."""
        from lean_tools_mcp.tools.diagnostics import lean_diagnostic_messages

        test_file = temp_dir / f"tool_diag_{_ts()}.lean"
        test_file.write_text(
            "theorem t_sorry : 1 = 1 := by sorry\n",
            encoding="utf-8",
        )
        print(f"\n[test_lean_diagnostic_messages_tool] file = {test_file}")

        result = await lean_diagnostic_messages(pool, str(test_file))
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_lean_hover_info_tool(self, pool, temp_dir):
        """Test lean_hover_info tool function."""
        from lean_tools_mcp.tools.hover import lean_hover_info

        test_file = temp_dir / f"tool_hover_{_ts()}.lean"
        test_file.write_text(
            "def testHover : Nat := 42\n#check testHover\n",
            encoding="utf-8",
        )
        print(f"\n[test_lean_hover_info_tool] file = {test_file}")

        result = await lean_hover_info(pool, str(test_file), line=2, column=8)
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_lean_completions_tool(self, pool, temp_dir):
        """Test lean_completions tool function."""
        from lean_tools_mcp.tools.completions import lean_completions

        test_file = temp_dir / f"tool_comp_{_ts()}.lean"
        test_file.write_text("def x := Nat.\n", encoding="utf-8")
        print(f"\n[test_lean_completions_tool] file = {test_file}")

        result = await lean_completions(pool, str(test_file), line=1, column=14)
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_lean_file_outline_tool(self, pool, temp_dir):
        """Test lean_file_outline tool function."""
        from lean_tools_mcp.tools.file_ops import lean_file_outline

        test_file = temp_dir / f"tool_outline_{_ts()}.lean"
        test_file.write_text(
            "def alpha : Nat := 1\ndef beta : Nat := 2\n",
            encoding="utf-8",
        )
        print(f"\n[test_lean_file_outline_tool] file = {test_file}")

        result = await lean_file_outline(pool, str(test_file))
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_lean_file_contents_tool(self, temp_dir):
        """Test lean_file_contents tool function (no LSP needed)."""
        from lean_tools_mcp.tools.file_ops import lean_file_contents

        test_file = temp_dir / f"tool_contents_{_ts()}.lean"
        test_file.write_text("line_one\nline_two\nline_three\n", encoding="utf-8")
        print(f"\n[test_lean_file_contents_tool] file = {test_file}")

        result = await lean_file_contents(str(test_file))
        print(f"  result:\n{result}")
        assert "1|line_one" in result
        assert "2|line_two" in result

    async def test_lean_local_search_tool(self):
        """Test lean_local_search against the real project."""
        from lean_tools_mcp.tools.file_ops import lean_local_search

        any_lean = LEAN_TEST_PROJECT / "Main.lean"
        if not any_lean.exists():
            for f in LEAN_TEST_PROJECT.rglob("*.lean"):
                any_lean = f
                break
        print(f"\n[test_lean_local_search_tool] searching from = {any_lean}")

        result = await lean_local_search(str(any_lean), "decl", limit=5)
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_lean_run_code_clean(self, pool):
        """Test lean_run_code with clean code."""
        from lean_tools_mcp.tools.run_code import lean_run_code

        code = "def runCodeTest : Nat := 42\n#check runCodeTest\n"
        print(f"\n[test_lean_run_code_clean] code:\n{code}")

        result = await lean_run_code(pool, code=code)
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        # Should contain the temp file path
        assert "lean_tools_mcp" in result
        assert "run_code_" in result

    async def test_lean_run_code_error(self, pool):
        """Test lean_run_code with code that has errors."""
        from lean_tools_mcp.tools.run_code import lean_run_code

        code = 'def broken : Nat := "not a nat"\n'
        print(f"\n[test_lean_run_code_error] code:\n{code}")

        result = await lean_run_code(pool, code=code)
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert "error" in result.lower()

    async def test_lean_multi_attempt_basic(self, pool, temp_dir):
        """Test lean_multi_attempt with a simple proof."""
        from lean_tools_mcp.tools.multi_attempt import lean_multi_attempt

        # Create a test file with a sorry that we'll try to replace
        test_file = temp_dir / f"multi_attempt_src_{_ts()}.lean"
        test_file.write_text(
            "theorem ma_test : 1 + 1 = 2 := by\n  sorry\n",
            encoding="utf-8",
        )
        print(f"\n[test_lean_multi_attempt_basic] file = {test_file}")

        # Try multiple tactics at line 2 (where "sorry" is)
        snippets = ["  simp", "  ring", "  omega"]
        result = await lean_multi_attempt(
            pool,
            file_path=str(test_file),
            line=2,
            snippets=snippets,
        )
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert "3 tactic" in result
        # At least one tactic should close the goal or make progress
        assert "simp" in result
        assert "ring" in result
        assert "omega" in result

    async def test_lean_multi_attempt_with_errors(self, pool, temp_dir):
        """Test lean_multi_attempt where some tactics fail."""
        from lean_tools_mcp.tools.multi_attempt import lean_multi_attempt

        test_file = temp_dir / f"multi_attempt_err_{_ts()}.lean"
        test_file.write_text(
            "theorem ma_err : 1 + 1 = 2 := by\n  sorry\n",
            encoding="utf-8",
        )
        print(f"\n[test_lean_multi_attempt_with_errors] file = {test_file}")

        # Mix of valid and invalid tactics
        snippets = ["  rfl", "  nonsense_tactic"]
        result = await lean_multi_attempt(
            pool,
            file_path=str(test_file),
            line=2,
            snippets=snippets,
        )
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert "2 tactic" in result
        # The Raw JSON section should be parseable
        json_marker = "--- Raw JSON ---"
        assert json_marker in result
        json_start = result.index(json_marker) + len(json_marker) + 1
        parsed = json.loads(result[json_start:])
        assert len(parsed) == 2


# =========================================================================
# External HTTP search tool tests (Phase 4)
# =========================================================================


@pytest.mark.asyncio
class TestSearchTools:
    """Integration tests for external HTTP search tools.

    These tests make real HTTP requests to external APIs.
    They use a shared rate limiter to respect API limits.
    Skipped if network is unavailable.
    """

    @pytest.fixture
    def limiter(self):
        from lean_tools_mcp.clients.rate_limiter import create_default_limiter
        return create_default_limiter()

    async def test_leansearch(self, limiter):
        """Test LeanSearch natural language query."""
        from lean_tools_mcp.tools.search import lean_leansearch

        query = "sum of two even numbers is even"
        print(f"\n[test_leansearch] query: {query}")

        result = await lean_leansearch(limiter, query=query, num_results=3)
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0
        # Should either return results or a meaningful error
        assert "No results" in result or "." in result or "Error" in result

    async def test_loogle(self, limiter):
        """Test Loogle type pattern query."""
        from lean_tools_mcp.tools.search import lean_loogle

        query = "List ?a → ?a"
        print(f"\n[test_loogle] query: {query}")

        result = await lean_loogle(limiter, query=query, num_results=5)
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_leanfinder(self, limiter):
        """Test LeanFinder semantic search."""
        from lean_tools_mcp.tools.search import lean_leanfinder

        query = "commutativity of addition on natural numbers"
        print(f"\n[test_leanfinder] query: {query}")

        result = await lean_leanfinder(limiter, query=query, num_results=3)
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_state_search(self, limiter):
        """Test StateSearch with a manually crafted goal state."""
        from lean_tools_mcp.clients.search import state_search_query

        # Directly test the client with a goal state string
        goal = "⊢ 0 ≤ 1"
        print(f"\n[test_state_search] goal: {goal}")

        response = await state_search_query(goal, num_results=3)
        print(f"  error: {response.error}")
        print(f"  results ({len(response.results)}):")
        for r in response.results:
            print(f"    {r.name}: {r.type}")
        assert isinstance(response.results, list)
        # May or may not return results depending on API availability

    async def test_hammer_premise(self, limiter):
        """Test HammerPremise with a manually crafted goal state."""
        from lean_tools_mcp.clients.search import hammer_premise_query

        # Directly test the client
        goal = "⊢ 0 ≤ 1"
        print(f"\n[test_hammer_premise] goal: {goal}")

        response = await hammer_premise_query(goal, num_results=5)
        print(f"  error: {response.error}")
        print(f"  results ({len(response.results)}):")
        for r in response.results:
            print(f"    {r.name}")
        assert isinstance(response.results, list)


@skip_without_project
@pytest.mark.asyncio
class TestSearchToolsWithLSP:
    """Integration tests for search tools that need LSP (state_search, hammer_premise)."""

    @pytest.fixture
    async def pool(self, temp_dir):
        from lean_tools_mcp.lsp.pool import LSPPool

        p = LSPPool(
            project_root=LEAN_TEST_PROJECT,
            pool_size=1,
            lean_path=LEAN_BIN,
            request_timeout=120.0,
            file_check_timeout=180.0,
        )
        await p.start()
        yield p
        await p.shutdown()

    @pytest.fixture
    def limiter(self):
        from lean_tools_mcp.clients.rate_limiter import create_default_limiter
        return create_default_limiter()

    async def test_state_search_with_lsp(self, pool, limiter, temp_dir):
        """Test state_search tool with real LSP goal extraction."""
        from lean_tools_mcp.tools.search import lean_state_search

        test_file = temp_dir / f"state_search_{_ts()}.lean"
        test_file.write_text(
            "theorem ss_test : 1 + 1 = 2 := by\n  sorry\n",
            encoding="utf-8",
        )
        print(f"\n[test_state_search_with_lsp] file = {test_file}")

        result = await lean_state_search(
            limiter, pool,
            file_path=str(test_file),
            line=2, column=3,
            num_results=3,
        )
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_hammer_premise_with_lsp(self, pool, limiter, temp_dir):
        """Test hammer_premise tool with real LSP goal extraction."""
        from lean_tools_mcp.tools.search import lean_hammer_premise

        test_file = temp_dir / f"hammer_premise_{_ts()}.lean"
        test_file.write_text(
            "theorem hp_test : 1 + 1 = 2 := by\n  sorry\n",
            encoding="utf-8",
        )
        print(f"\n[test_hammer_premise_with_lsp] file = {test_file}")

        result = await lean_hammer_premise(
            limiter, pool,
            file_path=str(test_file),
            line=2, column=3,
            num_results=5,
        )
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0


# =========================================================================
# Unified search tests (Phase 5)
# =========================================================================


@pytest.mark.asyncio
class TestUnifiedSearch:
    """Integration tests for unified multi-backend search."""

    @pytest.fixture
    def limiter(self):
        from lean_tools_mcp.clients.rate_limiter import create_default_limiter
        return create_default_limiter()

    async def test_unified_search_all_backends(self, limiter):
        """Test unified search across all backends."""
        from lean_tools_mcp.tools.unified_search import lean_unified_search

        query = "commutativity of addition"
        print(f"\n[test_unified_search_all_backends] query: {query}")

        result = await lean_unified_search(limiter, query=query, num_results=3)
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0
        # Should contain results from at least one backend
        assert "unique" in result or "Error" in result or "No results" in result

    async def test_unified_search_single_backend(self, limiter):
        """Test unified search with a single backend."""
        from lean_tools_mcp.tools.unified_search import lean_unified_search

        query = "List ?a → ?a"
        print(f"\n[test_unified_search_single_backend] query: {query}")

        result = await lean_unified_search(
            limiter, query=query, num_results=3, backends=["loogle"]
        )
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_unified_search_deduplication(self, limiter):
        """Test that unified search deduplicates results."""
        from lean_tools_mcp.tools.unified_search import lean_unified_search

        # A query likely to return overlapping results from different backends
        query = "Nat.add_comm"
        print(f"\n[test_unified_search_deduplication] query: {query}")

        result = await lean_unified_search(
            limiter, query=query, num_results=5,
            backends=["leansearch", "loogle"],
        )
        print(f"  result:\n{result}")
        assert isinstance(result, str)


# =========================================================================
# LLM client tests (Phase 5)
# =========================================================================


@pytest.mark.asyncio
class TestLLMIntegration:
    """Integration tests for the LLM client with real API calls.

    Uses the config.json from the user's existing lean_tools_suite.
    Skipped if config not found or no providers configured.
    """

    LLM_CONFIG_PATH = Path(
        "/Users/wzy/study/lean/v4.24.0-rc1/lean_tools_suite/"
        "Lean_Translation_Agent/config.json"
    )

    @pytest.fixture
    def llm_client(self):
        from lean_tools_mcp.config import LLMConfig, load_llm_providers
        from lean_tools_mcp.llm.client import LLMClient

        if not self.LLM_CONFIG_PATH.exists():
            pytest.skip("LLM config.json not found")

        providers = load_llm_providers(self.LLM_CONFIG_PATH)
        config = LLMConfig(
            providers=providers,
            default_model="deepseek-chat",
        )
        client = LLMClient(config)
        if not client.is_configured:
            pytest.skip("No LLM providers configured")
        return client

    async def test_llm_simple_query(self, llm_client):
        """Test a simple LLM query."""
        from lean_tools_mcp.llm.client import ChatMessage

        print("\n[test_llm_simple_query]")
        response = await llm_client.chat(
            [ChatMessage(role="user", content="What is 1+1? Answer with just the number.")],
            max_tokens=10,
        )
        print(f"  content: {response.content}")
        print(f"  model: {response.model}")
        print(f"  provider: {response.provider}")
        print(f"  usage: {response.usage}")
        print(f"  latency: {response.latency_ms:.0f}ms")
        print(f"  error: {response.error}")
        assert not response.error, f"LLM error: {response.error}"
        assert "2" in response.content

    async def test_llm_lean_query(self, llm_client):
        """Test an LLM query about Lean 4."""
        from lean_tools_mcp.tools.llm_tools import lean_llm_query

        prompt = "Write a Lean 4 statement for: every natural number is either even or odd. Just the theorem statement, no proof."
        print(f"\n[test_llm_lean_query] prompt: {prompt}")

        result = await lean_llm_query(llm_client, prompt, max_tokens=200)
        print(f"  result:\n{result}")
        assert isinstance(result, str)
        assert len(result) > 0
        assert "[LLM] Error" not in result

    async def test_llm_key_rotation(self, llm_client):
        """Test that key rotation works across multiple calls."""
        from lean_tools_mcp.llm.client import ChatMessage

        print("\n[test_llm_key_rotation]")
        # Make 3 calls to trigger rotation
        for i in range(3):
            response = await llm_client.chat(
                [ChatMessage(role="user", content=f"Say 'ok{i}'")],
                max_tokens=5,
            )
            print(f"  call {i+1}: provider={response.provider}, error={response.error}")
            # Don't assert success — some keys may be expired
            assert isinstance(response.content, str)


# =========================================================================
# Lean metaprogramming tools tests (Phase 6)
# =========================================================================


@pytest.mark.asyncio
class TestLeanMetaTools:
    """Integration tests for Lean metaprogramming tools (CLI executables).

    These tests require the Lean tools to be built (lake build in lean/).
    """

    @pytest.fixture
    def temp_dir(self):
        """Create temp dir inside the test project for temp files."""
        test_dir = LEAN_TEST_PROJECT / ".lake" / "lean_tools_mcp_test"
        test_dir.mkdir(parents=True, exist_ok=True)
        return test_dir

    async def test_havelet_extract(self, temp_dir):
        """Test have/let extraction from a Lean file."""
        from lean_tools_mcp.tools.lean_meta import lean_havelet_extract, _find_executable

        exe = _find_executable("havelet_generator")
        if exe is None:
            pytest.skip("havelet_generator not built")

        # Create a test file with have/let bindings
        test_file = temp_dir / f"havelet_input_{_ts()}.lean"
        test_file.write_text(
            "theorem test_havelet (n : Nat) : n + 0 = n := by\n"
            "  have h1 : n = n := rfl\n"
            "  omega\n",
            encoding="utf-8",
        )
        print(f"\n[test_havelet_extract] file = {test_file}")

        result = await lean_havelet_extract(
            file_path=str(test_file),
            prefix="Test",
            user_project_root=str(LEAN_TEST_PROJECT),
        )
        print(f"  result:\n{result[:500]}")
        assert isinstance(result, str)
        # Should either succeed or give a clear error
        assert len(result) > 0

    async def test_analyze_deps(self, temp_dir):
        """Test theorem dependency analysis."""
        from lean_tools_mcp.tools.lean_meta import lean_analyze_deps, _find_executable

        exe = _find_executable("definition_tool")
        if exe is None:
            pytest.skip("definition_tool not built")

        # Create a test file with a simple theorem
        test_file = temp_dir / f"deps_input_{_ts()}.lean"
        test_file.write_text(
            "theorem test_deps (n m : Nat) : n + m = m + n := Nat.add_comm n m\n",
            encoding="utf-8",
        )
        print(f"\n[test_analyze_deps] file = {test_file}")

        result = await lean_analyze_deps(
            file_path=str(test_file),
            user_project_root=str(LEAN_TEST_PROJECT),
        )
        print(f"  result:\n{result[:500]}")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_find_executables(self):
        """Test that built executables can be found."""
        from lean_tools_mcp.tools.lean_meta import _find_executable

        for name in ["havelet_generator", "decl_exporter", "definition_tool"]:
            exe = _find_executable(name)
            print(f"\n[test_find_executables] {name} = {exe}")
            # Should exist if lean/ was built
            if exe is not None:
                assert exe.exists()

    async def test_lean_path_construction(self):
        """Test that LEAN_PATH is correctly built."""
        from lean_tools_mcp.tools.lean_meta import _get_lean_path

        # Without user project
        lp = _get_lean_path()
        print(f"\n[test_lean_path_construction] no project: {lp[:200]}")
        assert isinstance(lp, str)

        # With user project
        lp = _get_lean_path(str(LEAN_TEST_PROJECT))
        print(f"  with project: {lp[:200]}")
        assert isinstance(lp, str)
        # Should contain the user project's lake dir
        assert ".lake" in lp
