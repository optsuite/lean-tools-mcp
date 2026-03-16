-- Author: Ziyu Wang
-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DefinitionTool/Main.lean
  -------------------------
  CLI entry point for the definition extractor tool.

  Usage: lake exe definition_tool <input.lean> [output.json]

  Analyzes the input Lean file, finds all theorem statements,
  and outputs JSON with all definitions/classes/structures used.
-/
import Lean
import Lean.Data.Json
import DefinitionTool.Core
import DefinitionTool.Analyzer

open Lean
open DefinitionTool
open DefinitionTool.Analyzer

unsafe def main (args : List String) : IO UInt32 := do
  if args.isEmpty then
    IO.eprintln "Usage: lake exe definition_tool <input.lean> [output.json]"
    IO.eprintln ""
    IO.eprintln "Analyzes a Lean file and extracts all definitions, classes, and structures"
    IO.eprintln "used in theorem statements. Outputs JSON to stdout or to the specified file."
    return 1

  let inputPath := System.FilePath.mk args.head!
  let outputPath := if args.length > 1 then some (System.FilePath.mk args[1]!) else none

  -- Check input file exists
  if !(← inputPath.pathExists) then
    IO.eprintln s!"Error: Input file not found: {inputPath}"
    return 1

  IO.eprintln s!"[definition_tool] Analyzing: {inputPath}"

  try
    let analysis ← analyzeFile inputPath

    IO.eprintln s!"[definition_tool] Found {analysis.theorems.size} theorem(s)"

    for thm in analysis.theorems do
      IO.eprintln s!"  - {thm.theoremName}: {thm.dependencies.size} dependencies"

    -- Output JSON
    let json := toJson analysis
    let jsonStr := json.pretty

    match outputPath with
    | some outPath =>
      IO.FS.writeFile outPath jsonStr
      IO.eprintln s!"[definition_tool] Output written to: {outPath}"
    | none =>
      IO.println jsonStr

    return (0 : UInt32)
  catch e =>
    IO.eprintln s!"Error: {e.toString}"
    return (1 : UInt32)
