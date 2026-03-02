-- Author: Lean Tools MCP Contributors
-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/TacticExtract.lean
  --------------------------------
  目的：从源文件按 RangePos 启发式抽取 `:= by ...` 的 tactic 区块。

  说明：
  * 仅当声明源码片段中存在 `:= by` 且 `by` 为独立 token 时生效；
  * term-style 证明、where/多段/嵌套更复杂的布局可能抽取不到（返回 none）。
  * 若需更高覆盖率，建议在 elaboration 期使用 InfoTree/TacticInfo 精确采集。
-/
import Lean
import DeclExporter.Core

open Lean
open DeclExporter

namespace DeclExporter.TacticExtract

/-- 判断字符是否可作为标识符的一部分（避免把 `by_cases` 误当成 `by`）。 -/
@[inline] private def isIdentChar (c : Char) : Bool :=
  c.isAlphanum || c = '_' || c = '\''

/-- 字符串的首字符（若有）。 -/
@[inline] private def firstChar? (s : String) : Option Char :=
  match s.data with
  | c :: _ => some c
  | []     => none

/-- 字符串的末字符（若有）。 -/
@[inline] private def lastChar? (s : String) : Option Char :=
  match s.data.reverse with
  | c :: _ => some c
  | []     => none

/-- 安全取第 `i` 行（0-based）。越界返回空串。 -/
@[inline] private def getLine (ls : List String) (i : Nat) : String :=
  match ls.drop i with
  | []      => ""
  | x :: _  => x

/-- 将 1-based 行列范围切下对应源码（按“字符列”计算）。 -/
private def sliceByRange (text : String) (rp : RangePos) : String :=
  let lines := text.splitOn "\n"
  let sL := rp.startLine - 1
  let eL := rp.endLine   - 1
  let sC := rp.startCol  - 1
  let eC := rp.endCol    - 1
  if sL > eL then "" else
  if sL = eL then
    let ln := getLine lines sL
    if eC < sC then "" else (ln.drop sC).take (eC - sC)
  else
    let first  := (getLine lines sL).drop sC
    let middle :=
      (List.range (eL - sL - 1)).map (fun k => getLine lines (sL + 1 + k))
    let last   := (getLine lines eL).take eC
    String.intercalate "\n" (first :: (middle ++ [last]))

/-- 从字符索引 `i` 开始在 `s` 中寻找前缀 `kw`（按字符计数），返回命中位置。 -/
partial def findFrom (s kw : String) (i : Nat) : Option Nat :=
  let sl := s.length
  let kl := kw.length
  if kl = 0 then some i else
  let rec go (j : Nat) : Option Nat :=
    if j + kl > sl then none
    else if (s.drop j).startsWith kw then some j
    else go (j + 1)
  go i

/-- 自 `j` 起向后寻找**独立 token** 的 `by`。命中返回其起始字符索引。 -/
partial def findByAfterAssignFrom (declSrc : String) (j : Nat) : Option Nat :=
  match findFrom declSrc "by" j with
  | none   => none
  | some q =>
    let okPrev :=
      match lastChar? (declSrc.take q) with
      | none   => true
      | some c => !(isIdentChar c)
    let okNext :=
      match firstChar? (declSrc.drop (q + 2)) with
      | none   => true
      | some c => !(isIdentChar c)
    if okPrev && okNext then some q else findByAfterAssignFrom declSrc (q + 1)

/-- 寻找 `:=` 之后的独立 `by`，返回命中的“by”起始字符索引。 -/
def findByAfterAssign (declSrc : String) : Option Nat :=
  let start :=
    match findFrom declSrc ":=" 0 with
    | some j => j + 2
    | none   => 0
  findByAfterAssignFrom declSrc start

/-- 基于声明的源文件与 RangePos 试图提取 `:= by ...` 的 tactic 文本。 -/
def extractTacticProofFromSource (filePath : String) (rp : RangePos) : IO (Option String) := do
  let text ← IO.FS.readFile filePath
  let decl := sliceByRange text rp
  match findByAfterAssign decl with
  | none   => return none
  | some j => return some ((decl.drop j).trim)

end DeclExporter.TacticExtract
