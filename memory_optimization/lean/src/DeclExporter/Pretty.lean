-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Pretty.lean
  -------------------------
  Responsibilities:
  * Provide a uniform expression-to-string strategy:
    - pretty: use `Meta.ppExpr` to obtain `Format`, then render it via `Std.Format.pretty`
    - raw:    use `toString` for a more stable structural representation
-/
import Lean
import DeclExporter.Core

open Lean Meta
open DeclExporter

namespace DeclExporter.Pretty

/-- Pretty-print under `MetaM`. `ppExpr` returns `Format`, then `Std.Format.pretty` renders it to `String`. -/
def ppExprStr (e : Expr) : MetaM String := do
  let fmt ← ppExpr e        -- fmt : Format
  pure (Std.Format.pretty fmt)

/-- Raw printing (not pretty), better suited for structural comparison and hashing. -/
@[inline] def rawExprStr (e : Expr) : String :=
  toString e

end DeclExporter.Pretty
