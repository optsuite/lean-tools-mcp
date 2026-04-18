-- Author: Zichen Wang
-- Contact: zichenwang25@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Ranges.lean
  -------------------------
  Responsibilities:
  * Infer source file paths by combining the search path with module-relative paths.
  * **Safe fallback**: the initial version does not return exact line/column
    positions (`pos = none`) to avoid `DeclarationRange` API differences across
    Lean versions. A pinned-version path can later add offset-to-line/column mapping.
-/
import Lean
import DeclExporter.Core
import DeclExporter.Inspect

open Lean
open System
open DeclExporter

namespace DeclExporter.Ranges

/-- Convert a module name like `"A.B.C"` to the relative path `A/B/C.lean`. -/
private def moduleRelPath (modName : String) (ext : String := "lean") : FilePath :=
  let parts  := modName.split (· = '.')
  let relStr := String.intercalate "/" parts
  (FilePath.mk relStr).withExtension ext

-- /-- Search `searchPathRef` root-by-root for `A/B/C.lean`. -/
-- def guessFileOfModule (modName : String) : IO (Option String) := do
--   let sp  ← searchPathRef.get
--   let rel := moduleRelPath modName "lean"
--   if (← rel.pathExists) then
--       return some rel.toString
--   for root in sp do
--     let p := root / rel
--     if (← p.pathExists) then
--       return some p.toString
--   return none


/-- Start from `getSrcSearchPath` and explicitly append sysroot source directories. -/
def getAugmentedSrcSearchPath : IO Lean.SearchPath := do
  let base    ← Lean.getSrcSearchPath      -- Only contains LEAN_SRC_PATH + appDir/../src/lean[/lake]
  let sysroot ← Lean.findSysroot
  let extra   : List FilePath := [
    sysroot / "src",            -- Common layout: …/toolchains/<tc>/src/{Init,Std,Lean,…}
    sysroot / "src" / "lean"    -- Some distributions place lake/lean sources under src/lean
  ]
  pure (base ++ extra)

/-- Find the `.lean` file for a module, preferring source paths and then falling
back to olean-adjacent paths (rare projects colocate source and olean files). -/
def guessFileOfModule (modName : String) : IO (Option String) := do
  let mod := stringToName modName

  -- 1) Source paths, including the appended sysroot/src directories.
  let srcSp ← getAugmentedSrcSearchPath
  if let some p ← Lean.SearchPath.findModuleWithExt srcSp "lean" mod then
    return some p.toString

  -- 2) Try the relative path under the current directory (e.g. LOG.foo -> ./LOG/foo.lean).
  let rel := moduleRelPath modName "lean"
  if (← rel.pathExists) then
    return some rel.toString

  -- 3) Fallback: also try the .olean search path, since some projects keep sources near lib/lean.
  let oleanSp ← Lean.searchPathRef.get
  if let some p ← Lean.SearchPath.findModuleWithExt oleanSp "lean" mod then
    return some p.toString

  return none


/-- Convert a `DeclarationRange` to the exported `RangePos`. -/
private def toRangePos (dr : DeclarationRange) : RangePos :=
  { startLine := dr.pos.line
    startCol  := dr.pos.column
    endLine   := dr.endPos.line
    endCol    := dr.endPos.column }

/-- Get the full `DeclarationRange` for a declaration in a given environment. -/
private def getDeclRange? (env : Environment) (decl : Name) : IO (Option DeclarationRange) := do
  /- We call `findDeclarationRanges?` inside `CoreM`, so only the read-only
     environment extension is needed. We manually construct a minimal
     `Core.Context` / `Core.State` to avoid pulling in Elaborator or Meta. -/
  let opts : Options := {}
  let ctx  : Core.Context :=
    { fileName       := "<decl-extractor>"
      fileMap        := "".toFileMap
      options        := opts
      currRecDepth   := 0
      maxRecDepth    := 1024
      ref            := Syntax.missing
      currNamespace  := Name.anonymous
      openDecls      := []
      initHeartbeats := 0
      maxHeartbeats  := Lean.Core.getMaxHeartbeats opts
      currMacroScope := 1
      -- catchRuntimeEx := true
      }
  let st   : Core.State :=
    { env            := env
      nextMacroScope := 1
      ngen           := {}
      traceState     := {}
      cache          := {}
      messages       := {}
      infoState      := {} }
  -- Run inside `CoreM`, obtain `DeclarationRanges`, and take its `range`
  -- field (the full declaration span, not `selectionRange`).
  let (r?, _st) ← (do (Lean.findDeclarationRanges? decl) : CoreM (Option DeclarationRanges)).toIO ctx st
  pure (r?.map (·.range))

/-- Combined query returning `(file?, pos?)`, with safe fallback to `none` on failure. -/
def fileAndPos? (env : Environment) (declName : Name) (moduleName : String)
    : IO (Option String × Option RangePos) := do
  let file?   ← guessFileOfModule moduleName
  let range?  ← getDeclRange? env declName
  let pos?    := range?.map toRangePos
  return (file?, pos?)


end DeclExporter.Ranges
