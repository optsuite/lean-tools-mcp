-- Author: Lean Tools MCP Contributors
-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Deps.lean
  -----------------------
  职责：
  * 从 Expr 中抽取“常量依赖”（Expr.const 的 Name 集合），不依赖不存在的 fold API。
  * 区分 deps_type / deps_value，外层组装时分别调用。
  说明：
  * 使用显式递归遍历 Expr 的所有构造，收集 .const n _。
  * 仅依赖 Lean 与 Std 的稳定接口，兼容 Lean 4.24.0。
-/
import Lean
import Std.Data.HashSet
import DeclExporter.Core

open Lean
open Std
open DeclExporter

namespace DeclExporter.Deps

/-- 显式递归遍历 `Expr`，收集出现的常量名（`Expr.const`）。 -/
partial def collectConstNames (e : Expr) (acc : HashSet Name := {}) : HashSet Name :=
  match e with
  | .const n _      => acc.insert n
  | .app f a        =>
      let acc := collectConstNames f acc
      collectConstNames a acc
  | .lam _ ty bd _  =>
      let acc := collectConstNames ty acc
      collectConstNames bd acc
  | .forallE _ d b _ =>
      let acc := collectConstNames d acc
      collectConstNames b acc
  | .letE _ ty v b _ =>
      let acc := collectConstNames ty acc
      let acc := collectConstNames v acc
      collectConstNames b acc
  | .mdata _ b      => collectConstNames b acc
  | .proj _ _ b     => collectConstNames b acc
  -- 其余不含子表达式或与常量无关的构造，直接返回累积集
  | .sort _         => acc
  | .lit _          => acc
  | .bvar _         => acc
  | .fvar _         => acc
  | .mvar _         => acc

/-- Expr → Array String（常量名去重、转 String）。 -/
def constDeps (e : Expr) : Array String :=
  (collectConstNames e {}).toArray.map nameToString

end DeclExporter.Deps
