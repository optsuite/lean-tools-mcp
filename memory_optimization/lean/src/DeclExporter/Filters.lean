-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Filters.lean
  --------------------------
  Responsibilities:
  * Pre-export filters for kind, module prefix, `sorry`, and internal-name exclusion.
  * No I/O or formatting concerns here; this module only performs boolean checks.
-/
import Lean
import DeclExporter.Core

open Lean
open DeclExporter

namespace DeclExporter.Filters

structure ExportFilter where
  kinds           : Option (Array String) := none   -- Export only these kinds.
  modulePrefixes  : Option (Array String) := none   -- Export only these module prefixes.
  excludeInternal : Bool := true                    -- Skip names that look internal.
  excludeSorry    : Bool := false                   -- Exclude declarations containing `sorry`.

/-- Conservatively detect whether a name looks internal or anonymous. -/
def isInternalName (n : Name) : Bool :=
  n.isAnonymous || (toString n).startsWith "_"

/-- Check whether the declaration kind matches the filter. -/
def kindAllowed (k : String) (cfg : ExportFilter) : Bool :=
  match cfg.kinds with
  | none      => true
  | some arr  => arr.contains k

/-- Check whether the module prefix is allowed by the filter. -/
def moduleAllowed (m : String) (cfg : ExportFilter) : Bool :=
  match cfg.modulePrefixes with
  | none      => true
  | some arr  => arr.any (fun pfx => m.startsWith pfx)

/-- Final normalized export predicate. -/
def allow (n : Name) (kind : String) (module : String) (hasSorry : Bool) (cfg : ExportFilter) : Bool :=
  (¬ cfg.excludeInternal ∨ ¬ isInternalName n) ∧
  kindAllowed kind cfg ∧
  moduleAllowed module cfg ∧
  (¬ cfg.excludeSorry ∨ ¬ hasSorry)

end DeclExporter.Filters
