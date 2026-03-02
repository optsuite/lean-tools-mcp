-- Author: Lean Tools MCP Contributors
-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Ranges.lean
  -------------------------
  职责：
  * 源文件路径推测（通过 SearchPath + 模块名拼相对路径）。
  * **安全降级**：首版不返回精确行列号（pos = none），避免不同 Lean 版本
    DeclarationRange API 差异；后续可在固定版本上补偏移→行列映射。
-/
import Lean
import DeclExporter.Core
import DeclExporter.Inspect

open Lean
open System
open DeclExporter

namespace DeclExporter.Ranges

/-- 将形如 `"A.B.C"` 的模块名转为相对路径 `A/B/C.lean` -/
private def moduleRelPath (modName : String) (ext : String := "lean") : FilePath :=
  let parts  := modName.split (· = '.')
  let relStr := String.intercalate "/" parts
  (FilePath.mk relStr).withExtension ext

-- /-- 在 `searchPathRef` 中逐个根目录拼接 `A/B/C.lean` 寻找文件 -/
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


/-- 在 `getSrcSearchPath` 基础上，**显式追加** sysroot 的源目录。 -/
def getAugmentedSrcSearchPath : IO Lean.SearchPath := do
  let base    ← Lean.getSrcSearchPath      -- 只含 LEAN_SRC_PATH + appDir/../src/lean[ /lake ]
  let sysroot ← Lean.findSysroot
  let extra   : List FilePath := [
    sysroot / "src",            -- 常见布局：…/toolchains/<tc>/src/{Init,Std,Lean,…}
    sysroot / "src" / "lean"    -- 少量发行版把 lake/lean 源放在 src/lean
  ]
  pure (base ++ extra)

/-- 找模块对应的 `.lean`，优先源路径，找不到再兜底 olean 路径（极少数工程源与 olean 共置） -/
def guessFileOfModule (modName : String) : IO (Option String) := do
  let mod := stringToName modName

  -- 1) 源路径（含我们追加的 sysroot/src）
  let srcSp ← getAugmentedSrcSearchPath
  if let some p ← Lean.SearchPath.findModuleWithExt srcSp "lean" mod then
    return some p.toString

  -- 2) 尝试当前目录下的相对路径 (e.g. LOG.foo -> ./LOG/foo.lean)
  let rel := moduleRelPath modName "lean"
  if (← rel.pathExists) then
    return some rel.toString

  -- 3) 兜底：在 .olean 搜索路径上再试试（有时源也放在 lib/lean 附近）
  let oleanSp ← Lean.searchPathRef.get
  if let some p ← Lean.SearchPath.findModuleWithExt oleanSp "lean" mod then
    return some p.toString

  return none


/-- 将 `DeclarationRange` 转为我们导出的 `RangePos`。 -/
private def toRangePos (dr : DeclarationRange) : RangePos :=
  { startLine := dr.pos.line
    startCol  := dr.pos.column
    endLine   := dr.endPos.line
    endCol    := dr.endPos.column }

/-- 在给定环境中获取某个声明的 `DeclarationRange`（整段范围）。 -/
private def getDeclRange? (env : Environment) (decl : Name) : IO (Option DeclarationRange) := do
  /- 我们在 `CoreM` 中调用 `findDeclarationRanges?`，只读环境扩展即可。
     这里手动构造最小的 `Core.Context` / `Core.State`，避免引入 Elaborator/Meta。 -/
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
  -- 在 CoreM 中运行：拿到 `DeclarationRanges` 后取其 `range` 字段（整段范围，不是 selectionRange）
  let (r?, _st) ← (do (Lean.findDeclarationRanges? decl) : CoreM (Option DeclarationRanges)).toIO ctx st
  pure (r?.map (·.range))

/-- 汇总：返回 (file?, pos?)。失败时安全降级为 `none`。 -/
def fileAndPos? (env : Environment) (declName : Name) (moduleName : String)
    : IO (Option String × Option RangePos) := do
  let file?   ← guessFileOfModule moduleName
  let range?  ← getDeclRange? env declName
  let pos?    := range?.map toRangePos
  return (file?, pos?)


end DeclExporter.Ranges
