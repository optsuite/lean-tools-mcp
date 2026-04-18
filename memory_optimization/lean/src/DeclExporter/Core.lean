-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Core.lean
  -----------------------
  Responsibilities:
  * Define the unified export record shape (a stable JSON schema).
  * Provide related lightweight helpers such as `kindOf`, version strings, and
    string/`Name` conversion.
  Notes:
  * Keep only data structures and lightweight helpers here, with no Meta dependency,
    so the module can be reused in any environment.
  * All `ConstantInfo` constructors are covered, including `quotInfo`.
  * Lean version strings come from `Lean.versionString`, which is available in Lean 4.24.0.
-/
import Lean
import Lean.Data.Json

open Lean

namespace DeclExporter

/-- Source range in line/column form. Use `none` when unavailable. -/
structure RangePos where
  startLine : Nat
  startCol  : Nat
  endLine   : Nat
  endCol    : Nat
deriving ToJson

/--
  Unified export record for top-level declarations. Fields are kept as stable as
  possible for long-term external consumption (for example by Rust or OLAP tooling).
  New fields can be added when needed, but they should preferably be appended at
  the end to reduce downstream breakage.
-/
structure DeclRec where
  name         : String             -- Fully qualified name.
  kind         : String             -- theorem/definition/axiom/opaque/inductive/ctor/recursor/quot
  module       : String             -- Owning module name.
  levelParams  : Array String       -- Universe parameters.
  type_pretty  : String             -- Pretty-printed type, intended for humans.
  type_raw     : String             -- Raw type rendering, more stable structurally.
  value_pretty : Option String      -- Pretty-printed value/proof term, if present.
  value_raw    : Option String      -- Raw value/proof rendering, if present.
  tactic_proof : Option String      -- Original tactic script text.
  has_proof    : Bool               -- Whether a value/proof term exists.
  has_sorry    : Bool               -- Whether the type or value contains `sorry`.
  deps_type    : Array String       -- Constant dependencies appearing in the type.
  deps_value   : Array String       -- Constant dependencies appearing in the value/proof.
  file         : Option String      -- Source file path, if available.
  pos          : Option RangePos    -- Line/column range, if available.
  lean_version : String             -- Lean version used during export.
  lib_version  : Option String      -- Exported library version, if available.
deriving ToJson

/-- Convert `Name` uniformly to `String`. -/
@[inline] def nameToString (n : Name) : String :=
  toString n

/-- Convert a module name like `"A.B.C"` into `Name`. -/
def stringToName (s : String) : Name :=
  (s.split (· = '.')).foldl (fun acc seg => Name.str acc seg) Name.anonymous

/--
  Classify `ConstantInfo` into a stable string representation.
  This includes `quotInfo` for Lean's built-in quotient-related constants.
-/
def kindOf (ci : ConstantInfo) : String :=
  match ci with
  | .axiomInfo    _ => "axiom"
  | .defnInfo     _ => "definition"
  | .thmInfo      _ => "theorem"
  | .opaqueInfo   _ => "opaque"
  | .quotInfo     _ => "quot"
  | .inductInfo   _ => "inductive"
  | .ctorInfo     _ => "ctor"
  | .recInfo      _ => "recursor"

/-- Return the current Lean version string (available in Lean 4.24.0). -/
def currentLeanVersion : String :=
  Lean.versionString

end DeclExporter
