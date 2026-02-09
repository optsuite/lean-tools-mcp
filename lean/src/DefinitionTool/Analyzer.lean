/-
  DefinitionTool/Analyzer.lean
  -----------------------------
  Core analysis logic:
  1. Parse a Lean file and find all theorem statements
  2. Extract constants used in the theorem type (statement)
  3. For each constant, get its definition info, docstring, and location
-/
import Lean
import Lean.Parser
import Lean.Elab.Command
import Lean.Elab.InfoTree
import Lean.PrettyPrinter
import DefinitionTool.Core

open Lean Elab Meta IO

namespace DefinitionTool.Analyzer

/-- Get module name for a declaration -/
def moduleOf (env : Environment) (n : Name) : String :=
  match env.getModuleIdxFor? n with
  | some idx =>
      let arr := env.header.moduleNames
      (arr[idx.toNat]!).toString
  | none => "_unknown_"

/-- Convert module name to relative file path -/
private def moduleToRelPath (modName : String) (ext : String := "lean") : System.FilePath :=
  let parts := modName.split (· = '.')
  let relStr := String.intercalate "/" parts
  (System.FilePath.mk relStr).withExtension ext

/-- Augmented source search path including sysroot -/
def getAugmentedSrcSearchPath : IO SearchPath := do
  let base ← Lean.getSrcSearchPath
  let sysroot ← Lean.findSysroot
  let extra : List System.FilePath := [
    sysroot / "src",
    sysroot / "src" / "lean"
  ]
  pure (base ++ extra)

/-- Find source file for a module -/
def findModuleFile (modName : String) : IO (Option String) := do
  let mod := stringToName modName

  -- 1) Source path (including sysroot/src)
  let srcSp ← getAugmentedSrcSearchPath
  if let some p ← SearchPath.findModuleWithExt srcSp "lean" mod then
    return some p.toString

  -- 2) Try relative path
  let rel := moduleToRelPath modName "lean"
  if (← rel.pathExists) then
    return some rel.toString

  -- 3) Fallback: olean search path
  let oleanSp ← searchPathRef.get
  if let some p ← SearchPath.findModuleWithExt oleanSp "lean" mod then
    return some p.toString

  return none

/-- Convert DeclarationRange to RangeInfo -/
private def toRangeInfo (dr : DeclarationRange) : RangeInfo :=
  { startLine := dr.pos.line
    startCol  := dr.pos.column
    endLine   := dr.endPos.line
    endCol    := dr.endPos.column }

/-- Get declaration range for a constant -/
def getDeclRange? (env : Environment) (decl : Name) : IO (Option DeclarationRange) := do
  let opts : Options := {}
  let ctx : Core.Context :=
    { fileName       := "<definition-tool>"
      fileMap        := "".toFileMap
      options        := opts
      currRecDepth   := 0
      maxRecDepth    := 1024
      ref            := Syntax.missing
      currNamespace  := Name.anonymous
      openDecls      := []
      initHeartbeats := 0
      maxHeartbeats  := Lean.Core.getMaxHeartbeats opts
      currMacroScope := 1
    }
  let st : Core.State :=
    { env            := env
      nextMacroScope := 1
      ngen           := {}
      traceState     := {}
      cache          := {}
      messages       := {}
      infoState      := {} }
  let (r?, _) ← (findDeclarationRanges? decl : CoreM (Option DeclarationRanges)).toIO ctx st
  pure (r?.map (·.range))

/-- Collect all constant names from an Expr (type expression) -/
partial def collectConstNames (e : Expr) (acc : Std.HashSet Name := {}) : Std.HashSet Name :=
  match e with
  | .const n _       => acc.insert n
  | .app f a         =>
      let acc := collectConstNames f acc
      collectConstNames a acc
  | .lam _ ty bd _   =>
      let acc := collectConstNames ty acc
      collectConstNames bd acc
  | .forallE _ d b _ =>
      let acc := collectConstNames d acc
      collectConstNames b acc
  | .letE _ ty v b _ =>
      let acc := collectConstNames ty acc
      let acc := collectConstNames v acc
      collectConstNames b acc
  | .mdata _ b       => collectConstNames b acc
  | .proj _ _ b      => collectConstNames b acc
  | .sort _          => acc
  | .lit _           => acc
  | .bvar _          => acc
  | .fvar _          => acc
  | .mvar _          => acc

/-- Check if a name is internal (starts with _) or is a basic type -/
def isInternalOrBasic (n : Name) : Bool :=
  let s := toString n
  -- Filter out internal names
  s.startsWith "_" ||
  s.startsWith "Lean." ||
  -- Filter out very basic types
  n == ``Nat || n == ``Int || n == ``Bool || n == ``String ||
  n == `Prop || n == `Type || n == `Sort ||
  n == ``True || n == ``False ||
  n == ``And || n == ``Or || n == ``Not ||
  n == ``Eq || n == ``HEq ||
  n == ``Exists || n == ``Sigma ||
  n == ``Unit || n == ``PUnit ||
  -- Filter out basic functions
  n == ``id || n == ``Function.comp ||
  -- Membership is probably not interesting
  n == ``Membership.mem

/-- Check if constant is a class -/
def isClassDecl (env : Environment) (n : Name) : Bool :=
  Lean.isClass env n

/-- Check if constant is a structure -/
def isStructureDecl (env : Environment) (n : Name) : Bool :=
  (Lean.getStructureInfo? env n).isSome

/-- Get the kind of a constant with class/structure distinction -/
def getKind (env : Environment) (ci : ConstantInfo) : String :=
  let n := ci.name
  if isClassDecl env n then "class"
  else if isStructureDecl env n then "structure"
  else kindOfConstant ci

/-- Pretty print an expression -/
def ppExprStr (env : Environment) (opts : Options) (e : Expr) : IO String := do
  let coreCtx : Core.Context :=
    { options  := opts
      fileName := "<definition-tool>"
      fileMap  := FileMap.ofString "" }
  let coreSt : Core.State :=
    { env            := env
      nextMacroScope := 1
      ngen           := default
      traceState     := default
      cache          := default
      messages       := default
      infoState      := default
      snapshotTasks  := #[] }
  let mctx : Meta.Context := {}
  let mst  : Meta.State   := {}
  let (fmt, _, _) ← (PrettyPrinter.ppExpr e).toIO coreCtx coreSt mctx mst
  pure (Std.Format.pretty' fmt opts)

/-- Try to read lines from a file -/
def readLinesFromFile (path : String) (startLine endLine : Nat) : IO (Option String) := do
  try
    let content ← IO.FS.readFile (System.FilePath.mk path)
    let lines := content.splitOn "\n"
    let startIdx := startLine - 1  -- Convert to 0-indexed
    let endIdx := min endLine lines.length
    if startIdx < lines.length then
      let selectedLines := lines.drop startIdx |>.take (endIdx - startIdx)
      pure (some (String.intercalate "\n" selectedLines))
    else
      pure none
  catch _ =>
    pure none

/-- Try to find docstring range (lines before definition that start with docstring marker) -/
def findDocRangeInFile (path : String) (defStartLine : Nat) : IO (Option RangeInfo) := do
  try
    let content ← IO.FS.readFile (System.FilePath.mk path)
    let lines := content.splitOn "\n"
    if defStartLine < 2 || lines.length == 0 then
      return none
    -- Look for docstring ending at or just before the definition
    let docEndMarker := "-" ++ "/"
    let docStartMarker := "/" ++ "-"
    let mut docStart : Option Nat := none
    let mut docEnd : Option Nat := none
    let mut i := defStartLine - 2  -- Start from line before definition (0-indexed)

    -- First, find the closing marker of docstring
    while i < lines.length do
      let line := lines[i]!
      let trimmed := line.trim
      if trimmed.endsWith docEndMarker then
        docEnd := some (i + 1)  -- Convert back to 1-indexed
        break
      else if !trimmed.isEmpty && !trimmed.startsWith "@" && !trimmed.startsWith "#" then
        -- Non-empty line that's not a docstring ending or attribute
        break
      if i == 0 then break
      i := i - 1

    -- Then find the opening marker
    if let some endL := docEnd then
      i := endL - 1  -- Back to 0-indexed
      while i < lines.length do
        let line := lines[i]!
        if line.trim.startsWith docStartMarker then
          docStart := some (i + 1)  -- 1-indexed
          break
        if i == 0 then break
        i := i - 1

      match (docStart, docEnd) with
      | (some s, some e) => pure (some { startLine := s, startCol := 0, endLine := e, endCol := 0 })
      | _ => pure none
    else
      pure none
  catch _ =>
    pure none

/-- Get dependency info for a single constant -/
def getDependencyInfo (env : Environment) (opts : Options) (n : Name) : IO (Option DependencyInfo) := do
  match env.find? n with
  | none => pure none
  | some ci =>
    let kind := getKind env ci
    let modName := moduleOf env n
    let filePath ← findModuleFile modName
    let defRange ← getDeclRange? env n

    -- Get docstring
    let docStr ← Lean.findDocString? env n

    -- Get definition pretty printed
    let defStr ← ppExprStr env opts ci.type

    -- Get doc range from source file
    let docRange ← match (filePath, defRange) with
      | (some path, some range) => findDocRangeInFile path range.pos.line
      | _ => pure none

    pure (some {
      name       := nameToString n
      kind       := kind
      module     := modName
      filePath   := filePath
      defRange   := defRange.map toRangeInfo
      docRange   := docRange
      docString  := docStr
      definition := defStr
    })

/-- Analyze a single theorem and extract its dependencies -/
def analyzeTheorem (env : Environment) (opts : Options) (n : Name) (ci : ConstantInfo)
    (srcFilePath : String) : IO TheoremAnalysis := do
  let modName := moduleOf env n

  -- Get theorem statement (type)
  let stmt ← ppExprStr env opts ci.type

  -- Get theorem range
  let thmRange ← getDeclRange? env n

  -- Collect all constants used in the type
  let constNames := collectConstNames ci.type {}

  -- Filter and get dependency info
  let mut deps : Array DependencyInfo := #[]
  for cn in constNames.toArray do
    if !isInternalOrBasic cn then
      match ← getDependencyInfo env opts cn with
      | some info =>
        -- Only include definitions, classes, structures, inductives
        if info.kind == "definition" || info.kind == "class" ||
           info.kind == "structure" || info.kind == "inductive" then
          deps := deps.push info
      | none => pure ()

  pure {
    theoremName   := nameToString n
    theoremModule := modName
    filePath      := srcFilePath
    range         := thmRange.map toRangeInfo
    statement     := stmt
    dependencies  := deps
  }

/-- Simplified file elaboration -/
unsafe def elaborateFile (path : System.FilePath) (opts : Options := {}) :
    IO (Environment × FileMap × PersistentArray InfoTree) := do
  Lean.enableInitializersExecution
  let input ← IO.FS.readFile path
  let fileName := path.toString
  let inputCtx := Parser.mkInputContext input fileName
  let (header, parserState, messages0) ← Parser.parseHeader inputCtx
  let (envBefore, messages1) ← processHeader header opts messages0 inputCtx
  let cmdState := Command.mkState envBefore messages1 opts
  let cmdState := { cmdState with infoState := { enabled := true } }
  let st ← Elab.IO.processCommands inputCtx parserState cmdState
  let envAfter := st.commandState.env
  let trees := st.commandState.infoState.trees
  pure (envAfter, inputCtx.fileMap, trees)

/-- Analyze a file and extract all theorem dependencies -/
unsafe def analyzeFile (path : System.FilePath) : IO FileAnalysis := do
  initSearchPath (← findSysroot)

  -- Get absolute path
  let absPath ← IO.FS.realPath path
  let absPathStr := absPath.toString

  let (env, _fileMap, _trees) ← elaborateFile path
  let opts : Options := {}

  -- Find all theorems in the file's module
  let fileName := path.fileName.getD "unknown"
  let moduleName := (fileName.stripSuffix ".lean")

  -- Collect all theorems defined in this file
  let mut theorems : Array TheoremAnalysis := #[]

  for (n, ci) in env.constants.toList do
    match ci with
    | .thmInfo _ =>
      -- Check if this theorem is from our file (by checking module)
      let mod := moduleOf env n
      -- We check if the module matches or if it's from the current file
      if mod == moduleName || mod == "_unknown_" then
        let analysis ← analyzeTheorem env opts n ci absPathStr
        theorems := theorems.push analysis
    | _ => pure ()

  pure {
    filePath := absPathStr
    theorems := theorems
  }

end DefinitionTool.Analyzer
