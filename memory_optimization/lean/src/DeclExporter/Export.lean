-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Export.lean
  -------------------------
  Compose Inspect/Deps/Pretty/Ranges/Filters to produce `DeclRec` arrays.
  Also provides JSONL writers (one JSON object per line).
  Uses real pretty-printing (`Lean.PrettyPrinter.ppExpr`) and constructs
  `Core.Context` / `Core.State` / `Meta.Context` / `Meta.State` correctly.
-/
import Lean
import Lean.Data.Json
import Lean.PrettyPrinter
import Lean.Data.Format
import DeclExporter.Core
import DeclExporter.Inspect
import DeclExporter.Deps
import DeclExporter.Pretty
import DeclExporter.Ranges
import DeclExporter.Filters
import DeclExporter.TacticExtract

open Lean
open DeclExporter
open DeclExporter.Inspect
open DeclExporter.Deps
open DeclExporter.Pretty
open DeclExporter.Ranges
open DeclExporter.Filters

namespace DeclExporter.Export

/-- Pretty-print an `Expr` to `String` under the given `env` and `opts`. -/
private def ppExprStrIO (env : Environment) (opts : Options) (e : Expr) : IO String := do
  -- `Core.Context` must provide `fileName`, `fileMap`, and `options`.
  let coreCtx : Core.Context :=
    { options  := opts
      fileName := "<decl-extractor>"
      fileMap  := FileMap.ofString "" }
  -- Build `Core.State` explicitly because Lean does not provide `Inhabited Core.State`.
  let coreSt  : Core.State :=
    { env            := env
      nextMacroScope := 1
      ngen           := default
      traceState     := default
      cache          := default
      messages       := default
      infoState      := default
      snapshotTasks  := #[] }
  -- Meta context/state.
  let mctx : Meta.Context := {}
  let mst  : Meta.State   := {}
  -- True pretty-printing: `ppExpr : MetaM Format`.
  let (fmt, _, _) ← (Lean.PrettyPrinter.ppExpr e).toIO coreCtx coreSt mctx mst
  -- Render to `String` using the width settings from `opts`.
  pure (Std.Format.pretty' fmt opts)

/-- Convert one `ConstantInfo` into a `DeclRec`, producing both pretty and raw strings. -/
def constToRec (env : Environment) (opts : Options)
    (ci : ConstantInfo) (libVersion? : Option String := none) : IO DeclRec := do
  let n      := ci.name
  let k      := DeclExporter.kindOf ci
  let m      := moduleOf env n
  let lp     := levelParams ci
  let ty     := typeExpr ci
  let v?     := valueExpr? ci
  let hasP   := hasValue ci

  -- Detect whether the declaration contains `sorry`.
  let hasS : Bool := ty.hasSorry || (match v? with | some v => v.hasSorry | none => false)

  -- Dependencies, separated into type/value buckets.
  let depsTy := constDeps ty
  let depsVl := match v? with
                | some v => constDeps v
                | none   => #[]

  -- Rendering: pretty (`MetaM`) and raw (stable).
  let typePretty ← ppExprStrIO env opts ty
  let typeRaw    := rawExprStr ty

  -- Use `pure` inside the branches rather than `return`, otherwise later code becomes unreachable.
  let valuePretty? ← match v? with
    | some v =>
        let s ← ppExprStrIO env opts v
        pure (some s)
    | none   =>
        pure none

  -- This line is now reachable.
  let valueRaw := v?.map rawExprStr



  -- File and position, with safe fallback (`pos = none`).
  let (file?, pos?) ← fileAndPos? env n m

  -- let tacticProof? : Option String := none
  let tacticProof? ← match (file?, pos?) with
    | (some path, some rp) =>
        match v? with
        | some _ => DeclExporter.TacticExtract.extractTacticProofFromSource path rp
        | none   => pure none
    | _ => pure none

  -- Version metadata.
  let leanVer := currentLeanVersion

  pure {
    name         := nameToString n
    kind         := k
    module       := m
    levelParams  := lp
    type_pretty  := typePretty
    type_raw     := typeRaw
    value_pretty := valuePretty?
    value_raw    := valueRaw
    tactic_proof := tacticProof?
    has_proof    := hasP
    has_sorry    := hasS
    deps_type    := depsTy
    deps_value   := depsVl
    file         := file?
    pos          := pos?
    lean_version := leanVer
    lib_version  := libVersion?
  }

/-- Traverse the environment and produce `DeclRec`s, applying the export filter. -/
def exportAll (env : Environment) (opts : Options)
    (flt : ExportFilter := {}) (libVersion? : Option String := none) : IO (Array DeclRec) := do
  let mut out : Array DeclRec := #[]
  for (n, ci) in env.constants.toList do
    let kind := DeclExporter.kindOf ci
    let modn := Inspect.moduleOf env n
    let hasS := ci.type.hasSorry ||
                (match Inspect.valueExpr? ci with
                 | some v => v.hasSorry
                 | none   => false)
    if allow n kind modn hasS flt then
      let rec ← constToRec env opts ci libVersion?
      out := out.push rec
  pure out

/-- Write a `DeclRec` array as JSONL. -/
def writeJsonl (path : System.FilePath) (recs : Array DeclRec) : IO Unit := do
  IO.FS.withFile path .write fun h => do
    for r in recs do
      h.putStrLn (toJson r |>.compress)

end DeclExporter.Export
