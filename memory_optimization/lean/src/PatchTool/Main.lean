-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

import Lean
import PatchTool.Core

/-!
# PatchTool Main (Simplified)

Command-line interface for searching Lean code.

Usage:
  lake exe patch_tool search <file> <pattern>

This is a simplified version that focuses on search functionality.
Full AST-based patching will be added in future versions.
-/

open Lean
open PatchTool

/-- Print usage information -/
def printUsage : IO Unit := do
  IO.println "Usage: patch_tool search <file> <pattern>"
  IO.println ""
  IO.println "Search for declarations containing the given pattern."
  IO.println ""
  IO.println "Example:"
  IO.println "  lake exe patch_tool search MyFile.lean sorry"

/-- Handle search command -/
def handleSearch (filePath : String) (pattern : String) : IO UInt32 := do
  -- Check if file exists
  let path := System.FilePath.mk filePath
  let fileExists ← path.pathExists
  if !fileExists then
    IO.eprintln s!"Error: File not found: {filePath}"
    return 1

  -- Search for pattern
  let results ← searchInFile filePath pattern

  -- Print results
  IO.println (formatResults results pattern)

  return 0

/-- Main entry point -/
def main (args : List String) : IO UInt32 := do
  match args with
  | ["search", file, pattern] =>
      handleSearch file pattern

  | _ =>
      printUsage
      return 1
