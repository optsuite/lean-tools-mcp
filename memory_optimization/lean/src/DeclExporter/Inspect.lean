-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Inspect.lean
  --------------------------
  Responsibilities:
  * Enumerate `ConstantInfo`s from the environment and extract information that
    is directly tied to the declaration itself:
    - name, kind, module, level params, raw type/value expressions, and `has_proof`.
  * Keep this layer as a thin wrapper for stability and maintainability.

  Key Lean 4.24.0 compatibility notes:
  * `moduleNames` is accessed via array indexing `arr[i]!` to avoid deprecated `Array.get!`.
  * In Lean 4.24, `OpaqueVal` exposes `value : Expr` rather than `value?`.
  * `ci.levelParams : List Name`, so we convert with `toArray` and then map to `Array String`.
-/
import Lean
import DeclExporter.Core

open Lean
open DeclExporter

namespace DeclExporter.Inspect

/-- Get the module name from the environment, falling back to `"_unknown_"` on failure. -/
def moduleOf (env : Environment) (n : Name) : String :=
  match env.getModuleIdxFor? n with
  | some idx =>
      -- 4.24: header.moduleNames : Array Name
      let arr := env.header.moduleNames
      -- Use indexed access `arr[i]!` rather than `Array.get!`.
      (arr[idx.toNat]!).toString
  | none     => "_unknown_"

/-- Determine whether a declaration carries a value (`theorem`/`definition`/`opaque`). -/
def hasValue (ci : ConstantInfo) : Bool :=
  match ci with
  | .defnInfo _   => true
  | .thmInfo _    => true
  | .opaqueInfo _ => true   -- Lean 4.24: `OpaqueVal` has `value : Expr`.
  | _             => false

/-- Extract the type `Expr`. -/
def typeExpr (ci : ConstantInfo) : Expr :=
  ci.type

/-- Extract the value/proof `Expr`, returning `none` when unavailable. -/
def valueExpr? (ci : ConstantInfo) : Option Expr :=
  match ci with
  | .defnInfo d   => some d.value
  | .thmInfo  t   => some t.value
  | .opaqueInfo o => some o.value    -- Lean 4.24 uses `value`, not `value?`.
  | _             => none

/-- Extract level parameters. In Lean 4.24 this is `List Name`, converted here to `Array String`. -/
def levelParams (ci : ConstantInfo) : Array String :=
  (ci.levelParams.map (·.toString)).toArray

end DeclExporter.Inspect
