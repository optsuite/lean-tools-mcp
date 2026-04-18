# Syntax-Aware Code Patching

这个工具使用 Lean 元编程来进行语法感知的代码修改，替代了原来基于字符串处理的 `patch.py`。

## 问题：为什么需要语法感知的修改？

### 原来的问题（字符串处理）

`patch.py` 使用 Python 字符串操作：

```python
# patch.py 第 122 行
lines = content.split("\n")

# patch.py 第 158 行
idx = content.find(search, start)
```

**问题**：
1. ❌ **不安全**：可能破坏 Lean 语法结构
2. ❌ **不准确**：无法理解语法树，可能在注释、字符串内部误操作
3. ❌ **脆弱**：依赖行号和文本匹配，格式变化就会失败

**例子**：
```lean
-- 原始代码
theorem foo : 1 = 1 := by
  rfl

-- 如果用字符串替换 "rfl" → "sorry"
-- 可能会误改注释中的 "rfl"：
-- This proof uses rfl  ← 这里也会被改！
```

### 新方案（语法感知）

使用 Lean 元编程操作抽象语法树（AST）：

```lean
-- PatchTool/Core.lean
def replaceSyntax (original : Syntax) (target : Syntax) (replacement : Syntax) : Syntax :=
  if original == target then
    replacement
  else
    match original with
    | Syntax.node info kind args =>
        let newArgs := args.map (fun child => replaceSyntax child target replacement)
        Syntax.node info kind newArgs
    | _ => original
```

**优点**：
1. ✅ **安全**：只修改语法树节点，不会破坏结构
2. ✅ **准确**：理解 Lean 语法，不会误改注释或字符串
3. ✅ **健壮**：对格式变化不敏感

---

## 架构

### Lean 端（元编程工具）

```
memory_optimization/lean/src/PatchTool/
├── Core.lean      # 核心语法树操作
└── Main.lean      # 命令行入口
```

**功能**：
- 解析 Lean 文件为语法树
- 搜索匹配的语法节点
- 替换语法节点
- 格式化回源代码

### Python 端（MCP 工具）

```
lean_tools_mcp/tools/
├── patch.py         # 旧的字符串处理（保留兼容）
└── patch_syntax.py  # 新的语法感知包装器
```

**功能**：
- 调用 Lean 工具
- 提供 MCP 友好的接口
- 向后兼容旧 API

---

## 使用方法

### 1. 构建 Lean 工具

```bash
cd /Users/wzy/study/lean/lean-tools-mcp/memory_optimization/lean
lake build patch_tool
```

### 2. Python API

#### 方法 A：按名称替换

```python
from lean_tools_mcp.tools.patch_syntax import lean_patch_by_name

result = await lean_patch_by_name(
    file_path="/path/to/file.lean",
    old_name="old_theorem",
    new_name="new_theorem",
    user_project_root="/path/to/project"
)
print(result)
```

#### 方法 B：按内容替换

```python
from lean_tools_mcp.tools.patch_syntax import lean_patch_by_content

result = await lean_patch_by_content(
    file_path="/path/to/file.lean",
    search_text="theorem foo",
    replacement_file="/path/to/replacement.lean",
    user_project_root="/path/to/project"
)
print(result)
```

#### 方法 C：搜索声明

```python
from lean_tools_mcp.tools.patch_syntax import lean_search_declarations

result = await lean_search_declarations(
    file_path="/path/to/file.lean",
    pattern="sorry",
    user_project_root="/path/to/project"
)
print(result)
```

#### 方法 D：向后兼容 API

```python
from lean_tools_mcp.tools.patch_syntax import lean_apply_patch_syntax

# 替代旧的 lean_apply_patch
result = await lean_apply_patch_syntax(
    file_path="/path/to/file.lean",
    new_content="theorem foo : 1 = 1 := by sorry",
    search="theorem foo",
    user_project_root="/path/to/project"
)
```

### 3. 命令行使用

```bash
# 重命名声明
lake exe patch_tool replace-name MyFile.lean old_theorem new_theorem

# 替换内容
lake exe patch_tool replace-content MyFile.lean "theorem foo" replacement.lean

# 搜索声明
lake exe patch_tool search MyFile.lean sorry
```

---

## 迁移指南

### 从 `patch.py` 迁移到 `patch_syntax.py`

**旧代码**：
```python
from lean_tools_mcp.tools.patch import lean_apply_patch

result = await lean_apply_patch(
    file_path=path,
    new_content=new_code,
    search=old_code,
)
```

**新代码**（推荐）：
```python
from lean_tools_mcp.tools.patch_syntax import lean_patch_by_content

# 先创建临时文件保存 new_code
temp_file = "/tmp/replacement.lean"
Path(temp_file).write_text(new_code)

result = await lean_patch_by_content(
    file_path=path,
    search_text=old_code,
    replacement_file=temp_file,
    user_project_root=project_root
)
```

**新代码**（兼容 API）：
```python
from lean_tools_mcp.tools.patch_syntax import lean_apply_patch_syntax

# 完全兼容旧 API
result = await lean_apply_patch_syntax(
    file_path=path,
    new_content=new_code,
    search=old_code,
    user_project_root=project_root
)
```

---

## 性能对比

| 方案 | 准确性 | 速度 | 健壮性 |
|------|--------|------|--------|
| 字符串处理 | ❌ 低 | ✅ 快 | ❌ 脆弱 |
| 语法感知 | ✅ 高 | ⚠️ 中等 | ✅ 健壮 |

**注意**：语法感知方案需要解析整个文件，所以比字符串处理慢一些，但准确性和健壮性大大提高。

---

## 限制和未来改进

### 当前限制

1. **只支持替换第一个匹配**
   - `occurrence` 参数还未实现
   - 未来会支持替换第 N 个匹配

2. **重命名功能未完成**
   - `replace-name` 模式只能搜索，不能真正重命名
   - 需要实现跨文件的引用更新

3. **格式化可能改变**
   - 使用 Lean 的 pretty printer 重新格式化
   - 可能与原始格式略有不同

### 未来改进

1. **支持多次替换**
   ```python
   result = await lean_patch_by_content(
       file_path=path,
       search_text=pattern,
       replacement_file=repl,
       occurrence=2  # 替换第 2 个匹配
   )
   ```

2. **支持批量操作**
   ```python
   result = await lean_patch_batch(
       file_path=path,
       patches=[
           {"search": "foo", "replace": "bar"},
           {"search": "baz", "replace": "qux"},
       ]
   )
   ```

3. **支持跨文件重命名**
   ```python
   result = await lean_rename_declaration(
       project_root=root,
       old_name="Foo.bar",
       new_name="Foo.baz",
       update_references=True  # 更新所有引用
   )
   ```

---

## 测试

创建测试文件：

```bash
cd /Users/wzy/study/lean/lean-tools-mcp

# 创建测试文件
cat > /tmp/test.lean << 'EOF'
import Mathlib

theorem foo : 1 = 1 := by
  rfl

theorem bar : 2 = 2 := by
  sorry
EOF

# 搜索包含 sorry 的声明
lake exe patch_tool search /tmp/test.lean sorry

# 创建替换内容
cat > /tmp/replacement.lean << 'EOF'
theorem bar : 2 = 2 := by
  rfl
EOF

# 替换
lake exe patch_tool replace-content /tmp/test.lean "theorem bar" /tmp/replacement.lean

# 查看结果
cat /tmp/test.lean
```

---

## 相关文件

- `memory_optimization/lean/src/PatchTool/Core.lean` - 核心实现
- `memory_optimization/lean/src/PatchTool/Main.lean` - CLI 入口
- `lean_tools_mcp/tools/patch_syntax.py` - Python 包装器
- `lean_tools_mcp/tools/patch.py` - 旧的字符串处理（保留）

---

## 总结

**推荐使用语法感知的 `patch_syntax.py`，而不是字符串处理的 `patch.py`**。

虽然语法感知方案稍慢，但它：
- ✅ 更准确（不会误改注释和字符串）
- ✅ 更健壮（对格式变化不敏感）
- ✅ 更安全（不会破坏语法结构）

这对于自动化代码修改工具来说至关重要。
