-- Contact: wangziyu-edu@stu.pku.edu.cn; optsuite@lean-tools-mcp
-- License: MIT

/-
  DeclExporter/TacticExtract.lean
  --------------------------------
  Goal: heuristically extract the `:= by ...` tactic block from source text
  using a `RangePos`.

  Notes:
  * This only succeeds when the declaration slice contains `:= by` and `by`
    appears as an independent token.
  * Term-style proofs, `where` clauses, multi-block layouts, and more deeply
    nested structures may fail to extract and simply return `none`.
  * For higher coverage, prefer precise collection from `InfoTree` / `TacticInfo`
    during elaboration.
-/
import Lean
import DeclExporter.Core

open Lean
open DeclExporter

namespace DeclExporter.TacticExtract

/-- Check whether a character can be part of an identifier, so `by_cases` is not mistaken for `by`. -/
@[inline] private def isIdentChar (c : Char) : Bool :=
  c.isAlphanum || c = '_' || c = '\''

/-- Return the first character of a string, if any. -/
@[inline] private def firstChar? (s : String) : Option Char :=
  match s.data with
  | c :: _ => some c
  | []     => none

/-- Return the last character of a string, if any. -/
@[inline] private def lastChar? (s : String) : Option Char :=
  match s.data.reverse with
  | c :: _ => some c
  | []     => none

/-- Safely get line `i` (0-based), returning the empty string when out of bounds. -/
@[inline] private def getLine (ls : List String) (i : Nat) : String :=
  match ls.drop i with
  | []      => ""
  | x :: _  => x

/-- Slice source text by a 1-based line/column range, measured in character columns. -/
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

/-- Search for prefix `kw` in `s` starting at character index `i`, returning the match position. -/
partial def findFrom (s kw : String) (i : Nat) : Option Nat :=
  let sl := s.length
  let kl := kw.length
  if kl = 0 then some i else
  let rec go (j : Nat) : Option Nat :=
    if j + kl > sl then none
    else if (s.drop j).startsWith kw then some j
    else go (j + 1)
  go i

/-- Search forward from `j` for `by` as an independent token, returning its start index. -/
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

/-- Find an independent `by` after `:=`, returning the start index of that `by`. -/
def findByAfterAssign (declSrc : String) : Option Nat :=
  let start :=
    match findFrom declSrc ":=" 0 with
    | some j => j + 2
    | none   => 0
  findByAfterAssignFrom declSrc start

/-- Try to extract the `:= by ...` tactic text from the declaration source using the file and `RangePos`. -/
def extractTacticProofFromSource (filePath : String) (rp : RangePos) : IO (Option String) := do
  let text ← IO.FS.readFile filePath
  let decl := sliceByRange text rp
  match findByAfterAssign decl with
  | none   => return none
  | some j => return some ((decl.drop j).trim)

end DeclExporter.TacticExtract
