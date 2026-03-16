-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Filters.lean
  --------------------------
  职责：
  * 导出前的选择器：kind/module 前缀/是否包含 sorry/是否跳过内部名。
  * 不涉及 I/O 与格式，只做布尔判断。
-/
import Lean
import DeclExporter.Core

open Lean
open DeclExporter

namespace DeclExporter.Filters

structure ExportFilter where
  kinds           : Option (Array String) := none   -- 仅导出这些种类
  modulePrefixes  : Option (Array String) := none   -- 仅导出这些模块前缀
  excludeInternal : Bool := true                    -- 跳过“看起来内部”的名字
  excludeSorry    : Bool := false                   -- 是否排除含 sorry 的声明

/-- 名称是否“看起来是内部/匿名”（保守检测） -/
def isInternalName (n : Name) : Bool :=
  n.isAnonymous || (toString n).startsWith "_"

/-- kind 是否匹配 -/
def kindAllowed (k : String) (cfg : ExportFilter) : Bool :=
  match cfg.kinds with
  | none      => true
  | some arr  => arr.contains k

/-- 模块前缀是否允许 -/
def moduleAllowed (m : String) (cfg : ExportFilter) : Bool :=
  match cfg.modulePrefixes with
  | none      => true
  | some arr  => arr.any (fun pfx => m.startsWith pfx)

/-- 归一化后的最终过滤器 -/
def allow (n : Name) (kind : String) (module : String) (hasSorry : Bool) (cfg : ExportFilter) : Bool :=
  (¬ cfg.excludeInternal ∨ ¬ isInternalName n) ∧
  kindAllowed kind cfg ∧
  moduleAllowed module cfg ∧
  (¬ cfg.excludeSorry ∨ ¬ hasSorry)

end DeclExporter.Filters
