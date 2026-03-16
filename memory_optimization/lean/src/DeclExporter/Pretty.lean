-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Pretty.lean
  -------------------------
  职责：
  * 统一“表达式字符串化”策略：
    - pretty：使用 Meta.ppExpr 得到 Format，再用 Std.Format.pretty 渲染为 String
    - raw：   使用 toString（结构稳定、便于后处理）
-/
import Lean
import DeclExporter.Core

open Lean Meta
open DeclExporter

namespace DeclExporter.Pretty

/-- pretty 打印（在 MetaM 下运行）。`ppExpr` 返回 `Format`，再用 `Std.Format.pretty` 转 `String`。 -/
def ppExprStr (e : Expr) : MetaM String := do
  let fmt ← ppExpr e        -- fmt : Format
  pure (Std.Format.pretty fmt)

/-- 原始打印（非 pretty），更适合结构比对与 hash。 -/
@[inline] def rawExprStr (e : Expr) : String :=
  toString e

end DeclExporter.Pretty
