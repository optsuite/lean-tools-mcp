/-
  DeclExporter/Export.lean
  -------------------------
  将 Inspect/Deps/Pretty/Ranges/Filters 组装起来，生成 DeclRec 数组；
  并提供 JSONL 写出函数（每行一个 JSON 对象）。
  使用真正 pretty（Lean.PrettyPrinter.ppExpr），并正确构造
  Core.Context / Core.State / Meta.Context / Meta.State。
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

/-- 在给定 `env` 与 `opts` 下对 `Expr` 做 pretty-print 并得到 `String`。 -/
private def ppExprStrIO (env : Environment) (opts : Options) (e : Expr) : IO String := do
  -- Core.Context：需提供 fileName / fileMap / options
  let coreCtx : Core.Context :=
    { options  := opts
      fileName := "<decl-extractor>"
      fileMap  := FileMap.ofString "" }
  -- Core.State：显式构造（Lean 没有 Inhabited Core.State）
  let coreSt  : Core.State :=
    { env            := env
      nextMacroScope := 1
      ngen           := default
      traceState     := default
      cache          := default
      messages       := default
      infoState      := default
      snapshotTasks  := #[] }
  -- Meta 上下文/状态
  let mctx : Meta.Context := {}
  let mst  : Meta.State   := {}
  -- 真正 pretty：ppExpr : MetaM Format
  let (fmt, _, _) ← (Lean.PrettyPrinter.ppExpr e).toIO coreCtx coreSt mctx mst
  -- 用 opts 中的宽度渲染为 String
  pure (Std.Format.pretty' fmt opts)

/-- 将单个 ConstantInfo 转为 DeclRec（产出 pretty/raw 两套字符串）。 -/
def constToRec (env : Environment) (opts : Options)
    (ci : ConstantInfo) (libVersion? : Option String := none) : IO DeclRec := do
  let n      := ci.name
  let k      := DeclExporter.kindOf ci
  let m      := moduleOf env n
  let lp     := levelParams ci
  let ty     := typeExpr ci
  let v?     := valueExpr? ci
  let hasP   := hasValue ci

  -- sorry 判定
  let hasS : Bool := ty.hasSorry || (match v? with | some v => v.hasSorry | none => false)

  -- 依赖（区分 type / value）
  let depsTy := constDeps ty
  let depsVl := match v? with
                | some v => constDeps v
                | none   => #[]

  -- 打印：pretty（MetaM）与 raw（稳定）
  let typePretty ← ppExprStrIO env opts ty
  let typeRaw    := rawExprStr ty

  -- 分支里用 `pure`，不要用 `return`，否则后续语句变成 unreachable
  let valuePretty? ← match v? with
    | some v =>
        let s ← ppExprStrIO env opts v
        pure (some s)
    | none   =>
        pure none

  -- 这行现在是可达的
  let valueRaw := v?.map rawExprStr



  -- 文件与位置（安全降级：pos = none）
  let (file?, pos?) ← fileAndPos? env n m

  -- let tacticProof? : Option String := none
  let tacticProof? ← match (file?, pos?) with
    | (some path, some rp) =>
        match v? with
        | some _ => DeclExporter.TacticExtract.extractTacticProofFromSource path rp
        | none   => pure none
    | _ => pure none

  -- 版本信息
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

/-- 遍历环境生成 DeclRec（应用过滤器） -/
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

/-- 将 DeclRec 数组写为 JSONL -/
def writeJsonl (path : System.FilePath) (recs : Array DeclRec) : IO Unit := do
  IO.FS.withFile path .write fun h => do
    for r in recs do
      h.putStrLn (toJson r |>.compress)

end DeclExporter.Export
