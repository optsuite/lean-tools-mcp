-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/Core.lean
  -----------------------
  职责：
  * 定义导出记录的统一数据结构（稳定 JSON Schema）；
  * 提供与之相关的轻量工具函数（如 kindOf、版本字符串、字符串与 Name 互转）。
  注意：
  * 仅放“数据结构 + 轻量工具”，不依赖 Meta，便于在任意环境复用。
  * 已补全 ConstantInfo 的所有构造子（包含 quotInfo）。
  * Lean 版本字符串使用 `Lean.versionString`（Lean 4.24.0 可用）。
-/
import Lean
import Lean.Data.Json

open Lean

namespace DeclExporter

/-- 位置范围（行列号）。若无法获取可为 none。 -/
structure RangePos where
  startLine : Nat
  startCol  : Nat
  endLine   : Nat
  endCol    : Nat
deriving ToJson

/--
  顶层声明导出的统一记录。字段尽量稳定，以便外部（Rust/OLAP）长期消费。
  可按需扩展字段，但建议在末尾追加，避免破坏下游兼容。
-/
structure DeclRec where
  name         : String             -- 完全限定名
  kind         : String             -- theorem/definition/axiom/opaque/inductive/ctor/recursor/quot
  module       : String             -- 所属模块名
  levelParams  : Array String       -- 宇称参数
  type_pretty  : String             -- 美化打印（人类可读）
  type_raw     : String             -- 原始打印（结构更稳）
  value_pretty : Option String      -- 值/证明项（pretty，若无则 none）
  value_raw    : Option String      -- 值/证明项原始打印（无则为 none）
  tactic_proof : Option String      -- tactic 脚本原文
  has_proof    : Bool               -- 是否存在值/证明项
  has_sorry    : Bool               -- 类型或值中是否含 sorry
  deps_type    : Array String       -- 类型中的常量依赖
  deps_value   : Array String       -- 值/证明项中的常量依赖
  file         : Option String      -- 源文件路径（可缺省）
  pos          : Option RangePos    -- 行列号（可缺省）
  lean_version : String             -- 采集时 Lean 版本号
  lib_version  : Option String      -- 采集目标库版本（可选：mathlib commit/hash 或自库版本）
deriving ToJson

/-- 统一把 `Name` 打印成 `String`。 -/
@[inline] def nameToString (n : Name) : String :=
  toString n

/-- 将形如 `"A.B.C"` 的模块名转为 `Name`。 -/
def stringToName (s : String) : Name :=
  (s.split (· = '.')).foldl (fun acc seg => Name.str acc seg) Name.anonymous

/--
  将 `ConstantInfo` 归类为稳定字符串。
  注意补全了 `quotInfo`（Lean 内置商类型相关常量）。
-/
def kindOf (ci : ConstantInfo) : String :=
  match ci with
  | .axiomInfo    _ => "axiom"
  | .defnInfo     _ => "definition"
  | .thmInfo      _ => "theorem"
  | .opaqueInfo   _ => "opaque"
  | .quotInfo     _ => "quot"
  | .inductInfo   _ => "inductive"
  | .ctorInfo     _ => "ctor"
  | .recInfo      _ => "recursor"

/-- 返回当前运行的 Lean 版本字符串（Lean 4.24.0 下可用）。 -/
def currentLeanVersion : String :=
  Lean.versionString

end DeclExporter
