-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Deps.lean
  -----------------------
  Responsibilities:
  * Extract constant dependencies from `Expr` values (the `Name`s in `Expr.const`)
    without relying on unavailable fold APIs.
  * Distinguish `deps_type` from `deps_value`, so callers can compute them separately.
  Notes:
  * Uses explicit recursive traversal over all `Expr` constructors to collect `.const n _`.
  * Depends only on stable Lean and Std interfaces, so it remains compatible with Lean 4.24.0.
-/
import Lean
import Std.Data.HashSet
import DeclExporter.Core

open Lean
open Std
open DeclExporter

namespace DeclExporter.Deps

/-- Explicitly recurse through an `Expr` and collect all constant names (`Expr.const`). -/
partial def collectConstNames (e : Expr) (acc : HashSet Name := {}) : HashSet Name :=
  match e with
  | .const n _      => acc.insert n
  | .app f a        =>
      let acc := collectConstNames f acc
      collectConstNames a acc
  | .lam _ ty bd _  =>
      let acc := collectConstNames ty acc
      collectConstNames bd acc
  | .forallE _ d b _ =>
      let acc := collectConstNames d acc
      collectConstNames b acc
  | .letE _ ty v b _ =>
      let acc := collectConstNames ty acc
      let acc := collectConstNames v acc
      collectConstNames b acc
  | .mdata _ b      => collectConstNames b acc
  | .proj _ _ b     => collectConstNames b acc
  -- The remaining constructors contain no subexpressions or no relevant constants.
  | .sort _         => acc
  | .lit _          => acc
  | .bvar _         => acc
  | .fvar _         => acc
  | .mvar _         => acc

/-- Convert an `Expr` to an `Array String` of deduplicated constant names. -/
def constDeps (e : Expr) : Array String :=
  (collectConstNames e {}).toArray.map nameToString

end DeclExporter.Deps
