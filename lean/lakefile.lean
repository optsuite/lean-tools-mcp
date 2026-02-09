import Lake
open Lake DSL

/-- Lean metaprogramming tools for the MCP server. -/
package «lean-tools-mcp» where
  srcDir := "src"

/-- DeclExporter: bulk declaration export to JSONL. -/
lean_lib DeclExporter where

/-- HaveletGenerator: extract have/let bindings as top-level decls. -/
lean_lib HaveletGenerator where

/-- DefinitionTool: analyze theorem dependencies. -/
lean_lib DefinitionTool where

/-- StateExpr: tactic that shows full expression tree. -/
lean_lib StateExpr where

/-- CLI: lake exe havelet_generator <input.lean> <output.lean> <Prefix> -/
lean_exe havelet_generator where
  root := `HaveletGenerator.Main
  supportInterpreter := true

/-- CLI: lake exe decl_exporter [--resume] OUT.jsonl Module.A [Module.B ...] -/
lean_exe decl_exporter where
  root := `DeclExporter.Main
  supportInterpreter := true

/-- CLI: lake exe definition_tool <input.lean> [output.json] -/
lean_exe definition_tool where
  root := `DefinitionTool.Main
  supportInterpreter := true
