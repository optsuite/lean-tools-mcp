-- Author: Lean Tools MCP Contributors
-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
havelet-generator (lake exe 版本，避开 .ofFVar(Id)Info 以及 ti.expr? / ti.lctx? 差异)
==================================================================================

用 `lake exe` 提取某 Lean 源文件中的所有局部 `have/let`，
并在指定路径生成一个独立 `.lean` 文件，包含闭合后的顶层 `def/theorem`。
-/

import Lean
import Lean.Meta.CollectFVars
open Lean Meta Elab

namespace HaveLet

/-- 清洗名字 -/
private def sanitize (s : String) : String :=
  let ok (c : Char) := c.isAlphanum || c == '_' || c == '·'
  let cleaned := s.foldl (fun acc c => acc.push (if ok c then c else '_')) ""
  if cleaned.isEmpty then "x" else cleaned

/-- Snapshot of a local `have/let` together with its context. -/
structure LocalBinding where
  fvarId  : FVarId
  userName : Name
  type     : Expr
  value    : Expr
  lctx     : LocalContext
  ctx      : ContextInfo
  parent?  : Option Name

/-- 收集 `LocalDecl` 中的 `have/let` -/
private structure CollectState where
  acc : Array LocalBinding := #[]

private def pushFromLCtx (lctx : LocalContext) (ctx : ContextInfo)
    (st : CollectState) : CollectState :=
  let ids := lctx.getFVarIds
  ids.foldl
    (init := st)
    (fun s fid =>
      match lctx.find? fid with
      | none => s
      | some decl =>
          match decl.value? true with
          | none => s
          | some val =>
              { acc := s.acc.push {
                  fvarId  := fid
                  userName := decl.userName
                  type     := decl.type
                  value    := val
                  lctx     := lctx
                  ctx      := ctx
                  parent?  := ctx.parentDecl?
                } })

private partial def collectFromTree
    (t : InfoTree) (ctx? : Option ContextInfo)
    (st : CollectState) : CollectState :=
  match t with
  | .context ctx t' =>
      collectFromTree t' (ctx.mergeIntoOuter? ctx?) st
  | .node info children =>
      let st :=
        match ctx? with
        | some ctx =>
            match info with
            | .ofTermInfo ti => pushFromLCtx ti.lctx ctx st
            | _              => st
        | none => st
      let childCtx? := info.updateContext? ctx?
      children.foldl (fun s child => collectFromTree child childCtx? s) st
  | .hole _ => st

private def dedupBindings (items : Array LocalBinding) : Array LocalBinding :=
  Id.run do
    let mut seen : Std.HashSet FVarId := {}
    let mut out : Array LocalBinding := #[]
    for bind in items.toList.reverse do
      if seen.contains bind.fvarId then
        pure ()
      else
        seen := seen.insert bind.fvarId
        out := out.push bind
    pure out.reverse

def collectLocals (trees : Array InfoTree) : Array LocalBinding :=
  dedupBindings <| (trees.foldl (fun st t => collectFromTree t none st) {}).acc

/-- 将一条 `let/have` 封装为顶层 `def/theorem` 源码字符串。 -/
def buildTopLevelDeclSrc
  (pref : String) (idx : Nat) (bind : LocalBinding) :
  IO (String × String) := do
  let (kw, tyStr, valStr) ←
    bind.ctx.runMetaM bind.lctx do
      let ty  ← instantiateMVars bind.type
      let val ← instantiateMVars bind.value
      let val ← zetaReduce val
      let lctx ← getLCtx
      let params ←
        (do
          let (_, s₁) ← ty.collectFVars.run ({} : Lean.CollectFVars.State)
          let (_, s₂) ← val.collectFVars.run s₁
          let s₂ ← Lean.CollectFVars.State.addDependencies s₂
          let used := s₂.fvarSet
          let mut arr : Array Expr := #[]
          for fid in lctx.getFVarIds do
            if used.contains fid then
              arr := arr.push (mkFVar fid)
          pure arr)
      let closedTy  ← mkForallFVars params ty
      let closedVal ← mkLambdaFVars params val
      let closedTy  ← instantiateMVars closedTy
      let closedVal ← instantiateMVars closedVal
      let isProp ← isProp closedTy
      let kw := if isProp then "theorem" else "def"
      let opts := (((← getOptions).setBool `pp.fullNames true).setBool `pp.privateNames true)
      let tyStr  := (← withOptions (fun _ => opts) <| ppExpr closedTy).pretty
      let valStr := (← withOptions (fun _ => opts) <| ppExpr closedVal).pretty
      pure (kw, tyStr, valStr)
  let base := sanitize bind.userName.toString
  let parentStr :=
    match bind.parent? with
    | some n =>
        let s := sanitize n.toString
        if s.isEmpty then "Anon" else s
    | none => "Anon"
  let full := s!"{pref}_{parentStr}_{base}_{idx}"
  let src := s!"{kw} {full} : {tyStr} :=\n  {valStr}\n"
  pure (full, src)

/-- 头尾 -/
def makeFooter : String := "\nend Extracted\n"

/-- 组合整份文件 -/
def buildFile (trees : Array InfoTree) (pref : String) (headerStr : String) : IO String := do
  let items := collectLocals trees
  let mut idx := 0
  let mut blocks : List String := []
  for item in items do
    idx := idx + 1
    let (_, src) ← buildTopLevelDeclSrc pref idx item
    blocks := src :: blocks
  let body := String.intercalate "\n" (blocks.reverse)
  pure <| headerStr ++ body ++ makeFooter

end HaveLet
