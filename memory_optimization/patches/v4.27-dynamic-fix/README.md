# Lean 4.27 动态文件检查修复补丁

这个补丁目录包含了修复 Lean LSP 动态文件检查问题的版本。

## 问题描述

原始的 Lean 4.27.0-rc1 LSP 对动态创建的临时文件（如 `.lake/lean_tools_mcp/*.lean`）不进行完整的类型检查。

## 修复内容

### Watchdog.lean

修改了 `handleDidOpen` 函数，添加了对动态文件的容错处理：

```lean
let mod ← try
  moduleFromDocumentUri doc.uri
catch _ =>
  -- 为临时文件创建合成的模块名
  let uriStr := doc.uri.toString
  let fileName := uriStr.splitOn "/" |>.getLast!.replace ".lean" ""
  pure (Name.mkSimple fileName)
```

**效果**：
- 如果文件在项目模块图中，正常处理
- 如果文件不在模块图中（临时文件），使用文件名作为模块名
- 这样 FileWorker 会被创建并进行完整的类型检查

## 使用方法

### 方法 1：使用构建脚本

```bash
cd /Users/wzy/study/lean/lean-tools-mcp

# 构建修复版本的 Lean
python memory_optimization/scripts/build_lean.py \
  --version v4.27.0-rc1 \
  --output ~/lean-builds/lean-4.27-dynamic-fix \
  --patch-version v4.27-dynamic-fix

# 使用修复版本的 Lean
export PATH=~/lean-builds/lean-4.27-dynamic-fix/bin:$PATH
lean --version  # 应该显示 v4.27.0-rc1
```

### 方法 2：手动应用补丁

```bash
# 1. 克隆 Lean 源码
git clone --depth 1 --branch v4.27.0-rc1 https://github.com/leanprover/lean4.git ~/lean-src

# 2. 应用补丁
cp memory_optimization/patches/v4.27-dynamic-fix/Watchdog.lean \
   ~/lean-src/src/Lean/Server/Watchdog.lean
cp memory_optimization/patches/v4.27-dynamic-fix/FileWorker.lean \
   ~/lean-src/src/Lean/Server/FileWorker.lean
cp memory_optimization/patches/v4.27-dynamic-fix/Import.lean \
   ~/lean-src/src/Lean/Elab/Import.lean
cp memory_optimization/patches/v4.27-dynamic-fix/Shell.lean \
   ~/lean-src/src/Lean/Shell.lean

# 3. 构建 Lean
cd ~/lean-src
mkdir -p build/release
cd build/release
cmake ../.. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

# 4. 安装
make install  # 或者直接使用 build/release/stage1/bin/lean
```

## 测试

使用修复版本的 Lean 后，测试动态文件检查：

```bash
# 设置使用修复版本的 Lean
export PATH=~/lean-builds/lean-4.27-dynamic-fix/bin:$PATH

# 在 LeanAgent2603 项目中测试
cd /Users/wzy/study/lean/v4.24.0-rc1/LeanAgent2603

# 运行测试
python3 test_run_code.py
```

**预期结果**：
- Test 1（正确代码）：✓ 成功
- Test 2（错误代码）：✗ 检测到错误
- Test 3（sorry 代码）：⚠ 检测到警告

## 与 CLI 模式的对比

| 特性 | CLI 模式 | 修复后的 LSP |
|------|---------|-------------|
| 准确性 | ✅ 准确 | ✅ 准确 |
| 首次运行 | 60-120s | 预计 10-20s |
| 后续运行 | 15-20s | 预计 2-5s |
| 需要重新编译 Lean | ❌ 不需要 | ✅ 需要 |

## 注意事项

1. **编译时间**：首次编译 Lean 需要 30-60 分钟
2. **磁盘空间**：Lean 源码和构建产物约需 5-10 GB
3. **依赖**：需要 CMake、C++ 编译器、GMP 库等

## 回退到原始版本

如果修复版本有问题，可以回退到 CLI 模式：

```bash
# 在 Python 代码中
os.environ["USE_LSP_FOR_RUN_CODE"] = "0"  # 使用 CLI 模式（默认）
```

或者使用系统的 Lean：

```bash
unset PATH  # 清除自定义 PATH
export PATH=/usr/local/bin:/usr/bin:/bin  # 使用系统 PATH
```

## 贡献

如果这个修复有效，可以考虑：
1. 向 Lean 上游提交 PR
2. 在 lean-tools-mcp 中默认使用修复版本
3. 提供预编译的二进制文件

## 相关文件

- `Watchdog.lean`：主要修改，添加动态文件容错
- `FileWorker.lean`：原始补丁（内存优化）
- `Import.lean`：原始补丁（内存优化）
- `Shell.lean`：原始补丁（内存优化）
