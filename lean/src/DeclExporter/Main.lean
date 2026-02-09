/-
  DeclExporter/Main.lean  (Lean 4.24)
  ------------------------------------
  * 流式写 JSONL，显示进度；
  * 仅导出 **模块名前缀** 命中的常量（例如传 "Mathlib" 则导出所有 Mathlib.*）；
  * 断点续跑：
      --resume      从已存在 JSONL 读出 {name} 去重并以追加模式写入
      --append      仅追加写，不读旧记录
      --progress=N  每 N 条打印一次进度（默认 2000）
-/
import Lean
import Lean.Data.Json
import Std
import DeclExporter.Core
import DeclExporter.Filters
import DeclExporter.Export
import DeclExporter.Inspect

-- #check Lean.Grind.Field

open Lean Std
open DeclExporter
open DeclExporter.Filters
open DeclExporter.Export
open DeclExporter.Inspect

/-- 简单 flags -/
structure CliFlags where
  append        : Bool := false
  resume        : Bool := false
  progressEvery : Nat  := 2000
deriving Inhabited

/-- 解析 `--append --resume --progress=NUM`，返回 (flags, 其余参数)。 -/
private partial def parseFlags (args : List String) : CliFlags × List String :=
  let rec go (fs : CliFlags) (restRev : List String) : List String → (CliFlags × List String)
  | [] => (fs, restRev.reverse)
  | a :: as =>
    if a == "--append" then go {fs with append := true} restRev as
    else if a == "--resume" then go {fs with resume := true} restRev as
    else if a.startsWith "--progress=" then
      let ns := a.drop ("--progress=".length)
      let n  := ns.toNat?.getD fs.progressEvery
      go {fs with progressEvery := n} restRev as
    else if a == "--progress" then
      match as with
      | b :: bs =>
        let n := b.toNat?.getD fs.progressEvery
        go {fs with progressEvery := n} restRev bs
      | [] =>
        go fs restRev []
    else
      go fs (a :: restRev) as
  go ({} : CliFlags) [] args

/-- 模块前缀匹配：传 "Mathlib" 则匹配 "Mathlib.*"。 -/
@[inline] def startsWithMod (modn : String) (mods : List String) : Bool :=
  mods.any (fun m => modn.startsWith m)

/-- 取名字的最后一段：`A.B.C` → `C`，`foo._simp_1_7` → `_simp_1_7` -/
@[inline] def tailName (n : Name) : Name :=
  match n with
  | .str _ s => Name.str .anonymous s
  | .num _ k => Name.num .anonymous k
  | .anonymous => .anonymous

/-- 读取已有 JSONL 中的 `"name"` 集合（用于 --resume 去重）。 -/
def readNameSetFromJsonl (path : System.FilePath) : IO (HashSet String) := do
  if !(← path.pathExists) then
    return HashSet.emptyWithCapacity (α := String)
  let content ← IO.FS.readFile path
  let mut acc : HashSet String := HashSet.emptyWithCapacity (α := String)
  -- JSONL 每行一个 JSON；我们用 splitOn "\n" 即可
  for ln in content.splitOn "\n" do
    let s := ln.trim
    if s.isEmpty then
      pure ()
    else
      match Json.parse s with
      | Except.ok j =>
        match j.getObjVal? "name" with
        | Except.ok (Json.str v) =>
          acc := acc.insert v
        | _ => pure ()
      | _ => pure ()
  return acc

def main (argv : List String) : IO UInt32 := do
  let (flags, args) := parseFlags argv
  if args.length < 2 then
    IO.eprintln "Usage: lake exe decl_exporter [--resume] [--append] [--progress=N] OUT.jsonl Module.A [Module.B ...]"
    return 1

  let out  := args.head!
  let mods := args.tail!
  if mods.isEmpty then
    IO.eprintln "No modules provided. Example: lake exe decl_exporter out.jsonl Mathlib"
    return 1

  -- 初始化搜索路径
  initSearchPath (← findSysroot)

  -- 导入模块以构建 Environment
  let imports : Array Import :=
    (mods.map (fun m => { module := DeclExporter.stringToName m : Import })).toArray
  let opts : Options := {}
  IO.eprintln s!"[decl_exporter] importing {imports.size} module(s) …"
  let env ← importModules imports opts
  IO.eprintln "[decl_exporter] import done."

  -- 过滤器（按需改）
  let flt : ExportFilter := { excludeInternal := true, excludeSorry := false }

  -- 先筛一遍目标常量（仅模块前缀匹配）
  let constList := env.constants.toList
  let targetNames : Array Name :=
    constList.foldl (init := (#[] : Array Name)) (fun acc (n, _ci) =>
      let modn := Inspect.moduleOf env n
      if startsWithMod modn mods then acc.push n else acc)

  let total := targetNames.size
  IO.eprintln s!"[decl_exporter] {total} decls to scan (by module prefix filter)."

  -- --resume：读旧 JSONL 的 name 集合，去重
  let outPath := System.FilePath.mk out
  let existing : HashSet String ←
    if flags.resume then
      let s ← readNameSetFromJsonl outPath
      IO.eprintln s!"[decl_exporter] resume: loaded {s.size} existing names from {out}"
      pure s
    else
      pure (HashSet.emptyWithCapacity (α := String))

  -- 选择写入模式
  let mode : IO.FS.Mode := if flags.resume || flags.append then .append else .write

  -- 流式写 JSONL
  IO.FS.withFile outPath mode fun h => do
    let mut scanned  : Nat := 0
    let mut exported : Nat := 0
    let mut skipped  : Nat := 0
    for n in targetNames do
      scanned := scanned + 1
      let nameStr := DeclExporter.nameToString n
      if flags.resume && existing.contains nameStr then
        skipped := skipped + 1
      else
        match env.constants.find? n with
        | none   => pure ()
        | some ci =>
          let kind  := DeclExporter.kindOf ci
          let modn  := Inspect.moduleOf env n
          let hasS  := ci.type.hasSorry || (Inspect.valueExpr? ci |>.elim false (fun v => v.hasSorry))

          let shortName := tailName n

          -- 过滤，如果最后的字段以"_"开头就过滤
          if allow shortName kind modn hasS flt then
          -- if allow n kind modn hasS flt then
            let rec ← constToRec env opts ci none
            h.putStrLn (toJson rec |>.compress)
            exported := exported + 1

      if scanned % flags.progressEvery == 0 || scanned == total then
        IO.eprintln s!"[decl_exporter] {scanned}/{total} scanned, {exported} exported, {skipped} skipped"

  IO.eprintln s!"[decl_exporter] done. wrote to {out}"
  return 0
