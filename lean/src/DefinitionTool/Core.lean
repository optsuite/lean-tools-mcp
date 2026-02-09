/-
  DefinitionTool/Core.lean
  -------------------------
  Core data structures for the Definition Extractor tool.

  This tool analyzes theorem statements and extracts all definitions,
  classes, and structures used within them.
-/
import Lean
import Lean.Data.Json

open Lean

namespace DefinitionTool

/-- Position range information -/
structure RangeInfo where
  startLine : Nat
  startCol  : Nat
  endLine   : Nat
  endCol    : Nat
deriving ToJson, FromJson, Repr

/-- Information about a definition/class/structure used in a theorem statement -/
structure DependencyInfo where
  name        : String         -- Fully qualified name (e.g. "Convex")
  kind        : String         -- "definition" / "class" / "structure" / "inductive" / "axiom"
  module      : String         -- Module path (e.g. "Mathlib.Analysis.Convex.Basic")
  filePath    : Option String  -- Full file path
  defRange    : Option RangeInfo -- Where the definition is (line range)
  docRange    : Option RangeInfo -- Where the docstring is (line range before definition)
  docString   : Option String  -- Natural language description
  definition  : String         -- The actual definition content (pretty printed)
deriving ToJson, FromJson, Repr

/-- Output structure for the analysis of a single theorem -/
structure TheoremAnalysis where
  theoremName   : String
  theoremModule : String
  filePath      : String       -- Full path to the source file
  range         : Option RangeInfo -- Line/column range of the theorem
  statement     : String       -- The theorem statement (before := by)
  dependencies  : Array DependencyInfo
deriving ToJson, FromJson, Repr

/-- Output structure for the whole file analysis -/
structure FileAnalysis where
  filePath    : String
  theorems    : Array TheoremAnalysis
deriving ToJson, FromJson, Repr

/-- Classify a ConstantInfo into a kind string -/
def kindOfConstant (ci : ConstantInfo) : String :=
  match ci with
  | .axiomInfo _    => "axiom"
  | .defnInfo _     => "definition"
  | .thmInfo _      => "theorem"
  | .opaqueInfo _   => "opaque"
  | .quotInfo _     => "quot"
  | .inductInfo i   =>
      -- Check if it's a structure or class (they are special inductives)
      if i.isRec then "inductive" else "inductive"
  | .ctorInfo _     => "constructor"
  | .recInfo _      => "recursor"

/-- Convert Name to String -/
@[inline] def nameToString (n : Name) : String :=
  toString n

/-- Convert String to Name -/
def stringToName (s : String) : Name :=
  (s.split (· = '.')).foldl (fun acc seg => Name.str acc seg) Name.anonymous

end DefinitionTool
