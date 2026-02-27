"""
Unit tests for configuration loading.

No Lean dependency.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from lean_tools_mcp.config import (
    LLMProviderEntry,
    ServerConfig,
    find_modified_lean_binary,
    load_config,
    load_llm_providers,
    read_lean_toolchain,
)


class TestLoadLLMProviders:
    def test_load_from_file(self, tmp_path: Path):
        config_data = {
            "api": {
                "openai": [
                    {"api_key": "sk-test-key", "api_base": "https://api.openai.com/v1"}
                ],
                "deepseek": [
                    {"api_key": "sk-ds-key", "api_base": "https://api.deepseek.com"}
                ],
            }
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        providers = load_llm_providers(config_file)
        assert "openai" in providers
        assert "deepseek" in providers
        assert len(providers["openai"]) == 1
        assert providers["openai"][0].api_key == "sk-test-key"
        assert providers["deepseek"][0].api_base == "https://api.deepseek.com"

    def test_load_missing_file(self):
        providers = load_llm_providers("/nonexistent/config.json")
        assert providers == {}

    def test_load_empty_providers(self, tmp_path: Path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"api": {}}))

        providers = load_llm_providers(config_file)
        assert providers == {}

    def test_skip_malformed_entries(self, tmp_path: Path):
        config_data = {
            "api": {
                "openai": [
                    {"api_key": "good-key", "api_base": "https://good.com"},
                    {"api_key": "no-base"},  # Missing api_base
                    {"api_base": "no-key"},  # Missing api_key
                ],
            }
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        providers = load_llm_providers(config_file)
        assert len(providers["openai"]) == 1


class TestLoadConfig:
    def test_defaults(self, tmp_path: Path):
        config = load_config(project_root=tmp_path)
        assert config.project_root == tmp_path
        assert config.transport == "stdio"
        assert config.lsp.pool_size == 2
        assert config.lsp.lean_path == "lean"

    def test_custom_project_root(self, tmp_path: Path):
        config = load_config(project_root=tmp_path / "my_project")
        assert config.project_root == tmp_path / "my_project"

    def test_env_lean_executable(self, tmp_path: Path, monkeypatch):
        """LEAN_EXECUTABLE env var should set lsp.lean_path."""
        monkeypatch.setenv("LEAN_EXECUTABLE", "/usr/local/bin/lean")
        config = load_config(project_root=tmp_path)
        assert config.lsp.lean_path == "/usr/local/bin/lean"

    def test_env_pool_size(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LEAN_LSP_POOL_SIZE", "8")
        config = load_config(project_root=tmp_path)
        assert config.lsp.pool_size == 8

    def test_env_lsp_timeout(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LEAN_LSP_TIMEOUT", "120")
        config = load_config(project_root=tmp_path)
        assert config.lsp.request_timeout == 120.0

    def test_env_transport_sse(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MCP_TRANSPORT", "sse")
        config = load_config(project_root=tmp_path)
        assert config.transport == "sse"

    def test_env_sse_host_port(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MCP_SSE_HOST", "0.0.0.0")
        monkeypatch.setenv("MCP_SSE_PORT", "9090")
        config = load_config(project_root=tmp_path)
        assert config.sse_host == "0.0.0.0"
        assert config.sse_port == 9090

    def test_env_llm_model(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_MODEL", "gpt-4")
        config = load_config(project_root=tmp_path)
        assert config.llm.default_model == "gpt-4"

    def test_default_sse_host_port(self, tmp_path: Path):
        config = load_config(project_root=tmp_path)
        assert config.sse_host == "127.0.0.1"
        assert config.sse_port == 8080

    def test_inprocess_default_off(self, tmp_path: Path):
        config = load_config(project_root=tmp_path)
        assert config.lsp.use_inprocess_workers is False

    def test_env_inprocess_workers(self, tmp_path: Path, monkeypatch):
        """LEAN_WORKER_INPROCESS=1 should enable in-process workers."""
        monkeypatch.setenv("LEAN_WORKER_INPROCESS", "1")
        config = load_config(project_root=tmp_path)
        assert config.lsp.use_inprocess_workers is True

    def test_env_inprocess_workers_off(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LEAN_WORKER_INPROCESS", "0")
        config = load_config(project_root=tmp_path)
        assert config.lsp.use_inprocess_workers is False

    def test_auto_detect_modified_binary(self, tmp_path: Path, monkeypatch):
        """When inprocess=1 and a matching build exists, auto-select it."""
        builds_dir = tmp_path / "lean-builds"
        (builds_dir / "v4.28.0" / "bin").mkdir(parents=True)
        lean_bin = builds_dir / "v4.28.0" / "bin" / "lean"
        lean_bin.write_text("#!/bin/sh\necho lean")
        lean_bin.chmod(0o755)

        project = tmp_path / "project"
        project.mkdir()
        (project / "lean-toolchain").write_text("leanprover/lean4:v4.28.0\n")

        monkeypatch.setenv("LEAN_WORKER_INPROCESS", "1")
        monkeypatch.setenv("LEAN_BUILDS_DIR", str(builds_dir))
        monkeypatch.delenv("LEAN_EXECUTABLE", raising=False)

        config = load_config(project_root=project)
        assert config.lsp.use_inprocess_workers is True
        assert config.lsp.lean_path == str(lean_bin)

    def test_auto_detect_fallback_when_no_build(self, tmp_path: Path, monkeypatch):
        """When inprocess=1 but no build exists, fall back to 'lean'."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "lean-toolchain").write_text("leanprover/lean4:v4.26.0\n")

        monkeypatch.setenv("LEAN_WORKER_INPROCESS", "1")
        monkeypatch.setenv("LEAN_BUILDS_DIR", str(tmp_path / "no-builds"))
        monkeypatch.delenv("LEAN_EXECUTABLE", raising=False)

        config = load_config(project_root=project)
        assert config.lsp.lean_path == "lean"


class TestReadLeanToolchain:
    def test_standard_format(self, tmp_path: Path):
        (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.28.0\n")
        assert read_lean_toolchain(tmp_path) == "v4.28.0"

    def test_bare_version(self, tmp_path: Path):
        (tmp_path / "lean-toolchain").write_text("v4.27.0\n")
        assert read_lean_toolchain(tmp_path) == "v4.27.0"

    def test_rc_version(self, tmp_path: Path):
        (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.29.0-rc2\n")
        assert read_lean_toolchain(tmp_path) == "v4.29.0-rc2"

    def test_missing_file(self, tmp_path: Path):
        assert read_lean_toolchain(tmp_path) is None

    def test_invalid_format(self, tmp_path: Path):
        (tmp_path / "lean-toolchain").write_text("nightly-2025-01-01\n")
        assert read_lean_toolchain(tmp_path) is None


class TestFindModifiedLeanBinary:
    def test_exact_match(self, tmp_path: Path):
        (tmp_path / "v4.28.0" / "bin").mkdir(parents=True)
        lean = tmp_path / "v4.28.0" / "bin" / "lean"
        lean.write_text("binary")
        assert find_modified_lean_binary(tmp_path, "v4.28.0") == lean

    def test_minor_version_fallback(self, tmp_path: Path):
        (tmp_path / "v4.29.0-rc2" / "bin").mkdir(parents=True)
        lean = tmp_path / "v4.29.0-rc2" / "bin" / "lean"
        lean.write_text("binary")
        assert find_modified_lean_binary(tmp_path, "v4.29.0") == lean

    def test_no_match(self, tmp_path: Path):
        (tmp_path / "v4.28.0" / "bin").mkdir(parents=True)
        (tmp_path / "v4.28.0" / "bin" / "lean").write_text("binary")
        assert find_modified_lean_binary(tmp_path, "v4.30.0") is None
