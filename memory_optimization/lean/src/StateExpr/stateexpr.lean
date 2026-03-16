-- Author: Ziyu Wang
-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

-- 我们需要导入 Lean 和 Json 库
import Lean
import Lean.Data.Json

-- 导入我们需要的所有元编程工具
open Lean Meta Elab Tactic Json

-- ==================================================================
--   第 1 步：定义可序列化 (ToJson) 的数据结构
-- ==================================================================

structure StateExprTree where
  display   : String
  fullExpr  : String
  type      : String
  children  : List StateExprTree
  deriving ToJson, Inhabited

structure StateHypothesis where
  name       : String
  display    : String
  typeTree   : StateExprTree
  valueTree  : Option StateExprTree
  deriving ToJson, Inhabited

structure StateTarget where
  display    : String
  typeTree   : StateExprTree
  deriving ToJson, Inhabited

structure StateGoalInfo where
  hypotheses : List StateHypothesis
  target     : StateTarget
  deriving ToJson, Inhabited

structure FullStateInfo where
  goals : List StateGoalInfo
  deriving ToJson, Inhabited


-- ==================================================================
--   第 2 步：重构 `buildExprTree` (返回 StateExprTree)
-- ==================================================================

partial def buildExprTree (e : Expr) : MetaM StateExprTree := do
  let displayStr := (← ppExpr e).pretty

  let (structureStr, typeStr) ← withOptions (
    ·.setBool `pp.explicit true
    |>.setBool `pp.notation false
    |>.setBool `pp.universes true
  ) do
    let s ← ppExpr e
    let t ← ppExpr (← inferType e)
    return (s.pretty, t.pretty)

  if let Expr.mdata _data expr := e then
    return ← buildExprTree expr

  let children ← match e with
    | Expr.app f a         => do pure [← buildExprTree f, ← buildExprTree a]
    | Expr.lam _name d b _info => do pure [← buildExprTree d, ← buildExprTree b]
    | Expr.forallE _name d b _info => do pure [← buildExprTree d, ← buildExprTree b]
    | Expr.letE _name t v b _info => do pure [← buildExprTree t, ← buildExprTree v, ← buildExprTree b]
    | Expr.proj _name _idx struct => do pure [← buildExprTree struct]
    | _ => pure []

  return {
    display   := displayStr,
    fullExpr  := structureStr,
    type      := typeStr,
    children  := children
  }


-- ==================================================================
--   第 3 步：创建 `buildStateInfo` (返回 FullStateInfo)
-- ==================================================================

def buildStateInfo : TacticM FullStateInfo := do
  let goals ← getGoals
  let mut goalInfos := []

  for goalId in goals do
    let goalInfo ← goalId.withContext do

      let lctx ← getLCtx
      let mut hyps := []
      for decl in lctx do
        if decl.isImplementationDetail then continue

        let typeTree ← buildExprTree decl.type

        let (valueTree, displayStr) ← if let .ldecl _ _ _ _ value _ _ := decl then
          let valueTree ← buildExprTree value
          let display := m!"let {decl.userName} := {← ppExpr value} : {← ppExpr decl.type}"
          pure (some valueTree, (← display.toString))
        else
          let display := m!"{decl.userName} : {← ppExpr decl.type}"
          pure (none, (← display.toString))

        hyps := {
          name       := decl.userName.toString,
          display    := displayStr,
          typeTree   := typeTree,
          valueTree  := valueTree
        } :: hyps

      let targetExpr ← goalId.getType
      let target := {
        display  := (← ppGoal goalId).pretty,
        typeTree := ← buildExprTree targetExpr
      }

      return { hypotheses := hyps.reverse, target := target }

    goalInfos := goalInfo :: goalInfos

  return { goals := goalInfos.reverse }


-- ==================================================================
--   第 4 步：创建新的策略和 InfoView 打印机
-- ==================================================================

partial def logTree (tree : StateExprTree) (indent : String) : TacticM Unit := do
  let notationStr := if tree.display != tree.fullExpr then
    m!"  (Notation: {tree.display})"
  else
    m!""

  logInfo m!"{indent}{tree.fullExpr} : {tree.type}{notationStr}"

  for child in tree.children do
    logTree child (indent ++ "  ")

def logStateInfo (info : FullStateInfo) : TacticM Unit := do
  logInfo m!"--- CURRENT STATE: FULL EXPRESSION TREE ---"

  for i in [0:info.goals.length] do
    let goal := info.goals[i]!
    logInfo m!"\n--- GOAL {i + 1} / {info.goals.length} ---"

    logInfo m!"\n--- Local Context (Hypotheses) ---"
    for hyp in goal.hypotheses do
      logInfo m!"\n--- Hypothesis: {hyp.name} ---"
      logInfo m!"Display: {hyp.display}"
      logInfo "Type Tree:"
      logTree hyp.typeTree "  "
      if let some vTree := hyp.valueTree then
        logInfo "Value Tree:"
        logTree vTree "  "

    logInfo m!"\n--- TARGET ---"
    logInfo m!"Display: {goal.target.display}"
    logInfo "Target Tree:"
    logTree goal.target.typeTree "  "

  logInfo m!"-------------------------------------------"


-- ----------------------------------------------------------------
--   新的策略语法 (已修复)
-- ----------------------------------------------------------------

syntax (name := showFullStateTree) "showFullStateTree" (str)? : tactic

@[tactic showFullStateTree]
def elabShowFullStateTree : Tactic := fun stx =>
  withMainContext do
    let stateInfo ← buildStateInfo

    -- stx[1] 是可选的 (str)? 部分
    match stx[1].getOptional? with
    | some strLitSyntax =>
      -- ✅✅✅ 修复：使用 `isStrLit?` 来解包 `Syntax` ✅✅✅
      match strLitSyntax.isStrLit? with
      | some pathString =>
          -- 成功！ pathString 现在是一个 `String`
          let path := pathString

          if let some dir := System.FilePath.parent path then
            IO.FS.createDirAll dir

          IO.FS.writeFile path (toJson stateInfo).pretty
          logInfo m!"State tree saved to: {path}"

      | none =>
          -- 用户提供了参数，但它不是一个字符串字面量
          logError m!"Tactic argument must be a string literal (e.g., \"path/file.json\")."

    | none =>
      -- --- 分支 2：没有参数，打印到 InfoView ---
      logStateInfo stateInfo

example (a b c x : Nat) (h : x = (a + b) - c) : True := by
  let y := a + b

  -- 测试 InfoView 打印
  showFullStateTree

  trivial

example (a b c x : Nat) (h : x = (a + b) - c) : True := by
  let y := a + b

  -- 测试 JSON 保存
  showFullStateTree "temp/state.json"

  trivial
