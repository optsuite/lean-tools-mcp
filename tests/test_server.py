"""
Unit tests for the MCP server tool registry.

No Lean dependency — tests tool definitions and routing.
"""

from __future__ import annotations

from lean_tools_mcp.server import TOOLS


class TestToolRegistry:
    """Test that all tools are properly registered."""

    EXPECTED_TOOLS = [
        "lean_goal",
        "lean_term_goal",
        "lean_diagnostic_messages",
        "lean_hover_info",
        "lean_completions",
        "lean_file_outline",
        "lean_file_contents",
        "lean_declaration_file",
        "lean_local_search",
        "lean_run_code",
        "lean_multi_attempt",
        "lean_apply_patch",
        "lean_leansearch",
        "lean_loogle",
        "lean_leanfinder",
        "lean_state_search",
        "lean_hammer_premise",
        "lean_unified_search",
        "lean_llm_query",
        "lean_havelet_extract",
        "lean_analyze_deps",
        "lean_export_decls",
    ]

    def test_all_tools_registered(self):
        """Verify all expected tools are in the TOOLS list."""
        tool_names = {t.name for t in TOOLS}
        for name in self.EXPECTED_TOOLS:
            assert name in tool_names, f"Tool '{name}' not registered"

    def test_tool_count(self):
        """Verify total number of registered tools."""
        assert len(TOOLS) == len(self.EXPECTED_TOOLS)

    def test_all_tools_have_input_schema(self):
        """Every tool must have an inputSchema with at least 'type' and 'properties'."""
        for tool in TOOLS:
            schema = tool.inputSchema
            assert "type" in schema, f"{tool.name} missing 'type' in schema"
            assert "properties" in schema, f"{tool.name} missing 'properties' in schema"

    def test_all_tools_have_required_fields(self):
        """Every tool must declare 'required' fields."""
        for tool in TOOLS:
            assert "required" in tool.inputSchema, (
                f"{tool.name} missing 'required' in schema"
            )

    TOOLS_WITHOUT_FILE_PATH = {
        "lean_run_code", "lean_leansearch", "lean_loogle", "lean_leanfinder",
        "lean_unified_search", "lean_llm_query", "lean_export_decls",
    }

    def test_all_tools_have_file_path(self):
        """Most tools should accept file_path as a required parameter."""
        for tool in TOOLS:
            if tool.name in self.TOOLS_WITHOUT_FILE_PATH:
                continue
            props = tool.inputSchema.get("properties", {})
            assert "file_path" in props, f"{tool.name} missing 'file_path' property"

    def test_tool_descriptions_not_empty(self):
        """Every tool must have a non-empty description."""
        for tool in TOOLS:
            assert tool.description, f"{tool.name} has empty description"
            assert len(tool.description) > 10, (
                f"{tool.name} description too short: {tool.description!r}"
            )

    def test_multi_attempt_accepts_tactics(self):
        """lean_multi_attempt must accept 'tactics' in its schema."""
        tool = next(t for t in TOOLS if t.name == "lean_multi_attempt")
        props = tool.inputSchema["properties"]
        assert "tactics" in props, "lean_multi_attempt missing 'tactics' property"
        assert "column" in props, "lean_multi_attempt missing 'column' property"
        assert "tactics" in tool.inputSchema["required"]
