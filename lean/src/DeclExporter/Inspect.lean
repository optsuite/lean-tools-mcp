-- Author: Lean Tools MCP Contributors
-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Inspect.lean
  --------------------------
  职责：
  * 从 Environment 中枚举 ConstantInfo，并提取与“声明本体”直接相关的信息：
    - 名称、种类、模块名、level params、type/value 的原始 Expr 与 has_proof 判定。
  * 仅做“轻薄包装”，保持稳定性与可维护性。

  兼容 Lean 4.24.0 的关键点：
  * moduleNames 使用数组索引写法 `arr[i]!`（避免 Array.get! 的弃用告警）。
  * OpaqueVal 在 4.24 固定有 `value : Expr`（不是 `value?`）。
  * `ci.levelParams : List Name`，需要 `toArray` 再映射成 `Array String`。
-/
import Lean
import DeclExporter.Core

open Lean
open DeclExporter

namespace DeclExporter.Inspect

/-- 从 Env 取模块名（失败时给占位 "_unknown_"） -/
def moduleOf (env : Environment) (n : Name) : String :=
  match env.getModuleIdxFor? n with
  | some idx =>
      -- 4.24: header.moduleNames : Array Name
      let arr := env.header.moduleNames
      -- 使用索引写法 `arr[i]!`（不要再用 Array.get!）
      (arr[idx.toNat]!).toString
  | none     => "_unknown_"

/-- 判定声明是否带值（定理/定义/opaque 都算“有值/证明项”） -/
def hasValue (ci : ConstantInfo) : Bool :=
  match ci with
  | .defnInfo _   => true
  | .thmInfo _    => true
  | .opaqueInfo _ => true   -- 4.24: OpaqueVal 有 `value : Expr`
  | _             => false

/-- 取类型 Expr -/
def typeExpr (ci : ConstantInfo) : Expr :=
  ci.type

/-- 取值/证明项 Expr（若无则 none） -/
def valueExpr? (ci : ConstantInfo) : Option Expr :=
  match ci with
  | .defnInfo d   => some d.value
  | .thmInfo  t   => some t.value
  | .opaqueInfo o => some o.value    -- 4.24: 这里是 `value`（非 `value?`）
  | _             => none

/-- 取 level params（4.24 为 List Name，这里转 Array String 以便序列化） -/
def levelParams (ci : ConstantInfo) : Array String :=
  (ci.levelParams.map (·.toString)).toArray

end DeclExporter.Inspect
