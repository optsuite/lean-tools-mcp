-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

import Lean

/-!
# PatchTool.Core (Simplified)

Simplified code search tool using basic string operations.

This version provides:
- Search for text patterns in Lean files
- Report matches with line numbers

Note: This is a simplified version. Full AST-based patching
requires more complex Lean 4 metaprogramming APIs.
-/

namespace PatchTool

open Lean

/-- Search result with location information -/
structure SearchResult where
  line : Nat
  text : String
  deriving Repr

/-- Check if a string contains a substring (simple implementation) -/
def stringContains (s : String) (pattern : String) : Bool :=
  (s.splitOn pattern).length > 1

/-- Search for a pattern in a Lean file -/
def searchInFile (filePath : String) (pattern : String) : IO (Array SearchResult) := do
  let content ← IO.FS.readFile filePath
  let lines := content.splitOn "\n" |>.toArray

  let mut results := #[]
  for i in [:lines.size] do
    let line := lines[i]!
    if stringContains line pattern then
      results := results.push {
        line := i + 1
        text := line
      }

  return results

/-- Format search results for display -/
def formatResults (results : Array SearchResult) (pattern : String) : String :=
  if results.isEmpty then
    s!"No matches found for pattern '{pattern}'"
  else
    let header := s!"Found {results.size} match(es) for pattern '{pattern}':\n\n"
    let body := String.join (results.toList.map fun r =>
      s!"Line {r.line}: {r.text}\n")
    header ++ body

end PatchTool
