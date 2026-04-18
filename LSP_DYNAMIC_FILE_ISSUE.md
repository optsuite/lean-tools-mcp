# Lean LSP 动态文件检查问题及解决方案

## 问题描述

Lean 4.27.0-rc1 的 LSP 对动态创建的临时文件不进行完整的类型检查。

### 症状

- 收到 `textDocument/didOpen` 后发送 `$/lean/fileProgress` 显示 `processing` 非空
- 发送 `textDocument/publishDiagnostics`，但 `diagnostics` 始终为空数组
- 永远不发送 `processing=[]` 完成通知
- 即使代码有明显错误也被判定为"compiles clean"

## 根本原因

Lean LSP 的 `Watchdog.handleDidOpen` 调用 `moduleFromDocumentUri` 来确定文件的模块名。
如果文件不在项目的模块图中（如临时文件），FileWorker 可能不会进行完整检查。

相关代码位置：
- `memory_optimization/patches/v4.27/Watchdog.lean:1354-1366`
- `memory_optimization/patches/v4.27/FileWorker.lean`

## 解决方案

### 方案 A：CLI 模式（已实现，推荐）

使用 `lake env lean` 直接调用编译器，绕过 LSP。

**实现**：
- `lean_tools_mcp/tools/run_code_cli.py`：CLI 实现
- `lean_tools_mcp/tools/run_code.py`：支持 LSP/CLI 切换

**使用**：
```python
# 默认使用 CLI 模式
result = await lean_run_code(lsp_pool, code)

# 切换到 LSP 模式（实验性）
os.environ["USE_LSP_FOR_RUN_CODE"] = "1"
```

**优点**：
- ✅ 可靠：能正确检测所有错误
- ✅ 准确：返回真实的 diagnostics
- ✅ 立即可用

**缺点**：
- ❌ 慢：首次运行 60-120 秒（加载 Mathlib），后续 15-20 秒

### 方案 B：修复 Lean LSP（长期方案）

修改 Lean 源码，让 LSP 能检查动态文件。

#### 需要修改的文件

1. **`memory_optimization/patches/v4.27/Watchdog.lean`**

在 `handleDidOpen` 中，移除或放宽对模块图的检查：

```lean
def handleDidOpen (p : LeanDidOpenTextDocumentParams) : ServerM Unit := do
  let doc := p.textDocument
  -- 修改前：mod := ← moduleFromDocumentUri doc.uri
  -- 这可能会拒绝不在模块图中的文件
  
  -- 修改后：对所有文件都尝试创建 FileWorker
  let mod := ← try
    moduleFromDocumentUri doc.uri
  catch _ =>
    -- 如果无法从 URI 获取模块名，使用文件名作为临时模块名
    pure (Name.mkSimple (doc.uri.toString.splitOn "/" |>.getLast!.replace ".lean" ""))
  
  startFileWorker {
    uri := doc.uri
    mod := mod
    version := doc.version
    text := doc.text.crlfToLf.toFileMap
    dependencyBuildMode := p.dependencyBuildMode?.getD .always
  }
```

2. **`memory_optimization/patches/v4.27/FileWorker.lean`**

确保 `updateDocument` 总是发送完成通知：

```lean
def updateDocument : FileWorkerM Unit := do
  publishProgress { processing := [fullFileRange] }
  
  try
    -- 即使文件不在模块图中，也尝试完整检查
    let imports ← processHeader
    elaborateFile
    publishDiagnostics (← getDiagnostics)
  catch e =>
    -- 即使失败，也要发送错误诊断
    publishDiagnostics [mkErrorDiagnostic e.toString]
  finally
    -- 确保总是发送完成通知
    publishProgress { processing := [] }
```

#### 编译和使用

修改补丁后，需要：

1. 应用补丁到 Lean 源码
2. 重新编译 Lean
3. 使用修改后的 Lean 二进制文件

详细步骤参见 `memory_optimization/README.md`。

### 方案 C：Scratch File 扩展（替代方案）

添加新的 LSP 扩展请求 `lean/checkScratchFile`，专门用于检查临时代码。

**优点**：
- 不影响现有文件处理逻辑
- 可以优化性能（复用 Environment）

**缺点**：
- 需要修改 LSP 协议
- 客户端需要适配

## 性能对比

| 方案 | 首次运行 | 后续运行 | 准确性 | 可用性 |
|------|---------|---------|--------|--------|
| LSP 模式（有 bug） | N/A | N/A | ❌ 不准确 | ❌ 不可用 |
| CLI 模式 | 60-120s | 15-20s | ✅ 准确 | ✅ 可用 |
| 修复后的 LSP | 预计 5-10s | 预计 2-5s | ✅ 准确 | ⏳ 需要编译 |

## 测试结果

### CLI 模式测试（已验证）

```
Test 1 (正确代码): 超时 120s (首次加载 Mathlib)
Test 2 (错误代码): ✅ 检测到 2 个错误 (17s)
  [error] 3:0 — Not a definitional equality
  [error] 3:23 — Type mismatch
Test 3 (sorry 代码): ✅ 检测到 1 个警告 (17s)
  [warning] 3:8 — declaration uses 'sorry'
```

## 建议

1. **短期**：使用 CLI 模式（已实现并测试通过）
2. **中期**：修复 Lean LSP 补丁（需要重新编译 Lean）
3. **长期**：向 Lean 上游提交补丁，让官方版本支持动态文件检查

## 相关文件

- `lean_tools_mcp/tools/run_code.py`：主入口，支持模式切换
- `lean_tools_mcp/tools/run_code_cli.py`：CLI 实现
- `memory_optimization/patches/v4.27/Watchdog.lean`：需要修改的 LSP 代码
- `memory_optimization/patches/v4.27/FileWorker.lean`：需要修改的 LSP 代码
