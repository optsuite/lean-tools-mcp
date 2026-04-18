#!/usr/bin/env python3
"""
测试语法感知的代码修改工具

这个脚本测试：
1. Lean 工具是否正确构建
2. Python 包装器是否正确导入
3. 基本功能是否工作
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# 添加 lean-tools-mcp 到路径
REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))


def test_lean_files_exist():
    """测试 Lean 源文件是否存在"""
    print("=== Test 1: Lean 源文件 ===")

    files = [
        "memory_optimization/lean/src/PatchTool/Core.lean",
        "memory_optimization/lean/src/PatchTool/Main.lean",
    ]

    all_exist = True
    for filepath in files:
        full_path = REPO_ROOT / filepath
        if full_path.exists():
            print(f"✅ {filepath}")
        else:
            print(f"❌ {filepath} 不存在")
            all_exist = False

    return all_exist


def test_lakefile_updated():
    """测试 lakefile 是否更新"""
    print("\n=== Test 2: lakefile.lean 更新 ===")

    lakefile = REPO_ROOT / "memory_optimization" / "lean" / "lakefile.lean"
    if not lakefile.exists():
        print("❌ lakefile.lean 不存在")
        return False

    content = lakefile.read_text()

    checks = [
        ("lean_lib PatchTool", "PatchTool 库定义"),
        ("lean_exe patch_tool", "patch_tool 可执行文件"),
        ("root := `PatchTool.Main", "正确的入口点"),
    ]

    all_passed = True
    for pattern, description in checks:
        if pattern in content:
            print(f"✅ {description}")
        else:
            print(f"❌ 缺少: {description}")
            all_passed = False

    return all_passed


def test_python_wrapper_exists():
    """测试 Python 包装器是否存在"""
    print("\n=== Test 3: Python 包装器 ===")

    wrapper = REPO_ROOT / "lean_tools_mcp" / "tools" / "patch_syntax.py"
    if not wrapper.exists():
        print("❌ patch_syntax.py 不存在")
        return False

    print("✅ patch_syntax.py 存在")

    # 测试导入
    try:
        from lean_tools_mcp.tools.patch_syntax import (
            lean_patch_by_name,
            lean_patch_by_content,
            lean_search_declarations,
            lean_apply_patch_syntax,
        )
        print("✅ 所有函数导入成功")
        return True
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return False


def test_documentation():
    """测试文档是否存在"""
    print("\n=== Test 4: 文档 ===")

    doc = REPO_ROOT / "SYNTAX_AWARE_PATCHING.md"
    if not doc.exists():
        print("❌ SYNTAX_AWARE_PATCHING.md 不存在")
        return False

    print("✅ SYNTAX_AWARE_PATCHING.md 存在")

    content = doc.read_text()

    checks = [
        ("## 问题：为什么需要语法感知的修改？", "问题说明"),
        ("## 架构", "架构说明"),
        ("## 使用方法", "使用说明"),
        ("## 迁移指南", "迁移指南"),
    ]

    all_passed = True
    for pattern, description in checks:
        if pattern in content:
            print(f"✅ 包含{description}")
        else:
            print(f"❌ 缺少{description}")
            all_passed = False

    return all_passed


async def test_build_tool():
    """测试构建 Lean 工具"""
    print("\n=== Test 5: 构建 Lean 工具 ===")

    lean_dir = REPO_ROOT / "memory_optimization" / "lean"
    if not lean_dir.exists():
        print("❌ Lean 目录不存在")
        return False

    print("ℹ️  尝试构建 patch_tool...")
    print("   (这可能需要几分钟)")

    try:
        proc = await asyncio.create_subprocess_exec(
            "lake", "build", "patch_tool",
            cwd=str(lean_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode == 0:
            print("✅ patch_tool 构建成功")
            return True
        else:
            print(f"❌ 构建失败 (exit {proc.returncode})")
            print(f"   stderr: {stderr.decode('utf-8', errors='replace')[:200]}")
            return False
    except asyncio.TimeoutError:
        print("⚠️  构建超时（5 分钟）")
        return False
    except FileNotFoundError:
        print("⚠️  lake 命令未找到（可能需要先安装 Lean）")
        return False
    except Exception as e:
        print(f"⚠️  构建出错: {e}")
        return False


async def test_basic_functionality():
    """测试基本功能"""
    print("\n=== Test 6: 基本功能测试 ===")

    # 检查可执行文件是否存在
    exe = REPO_ROOT / "memory_optimization" / "lean" / ".lake" / "build" / "bin" / "patch_tool"
    if not exe.exists():
        print("⚠️  patch_tool 可执行文件不存在，跳过功能测试")
        print("   请先运行: cd memory_optimization/lean && lake build patch_tool")
        return None

    # 创建测试文件
    test_content = """import Mathlib

theorem foo : 1 = 1 := by
  rfl

theorem bar : 2 = 2 := by
  sorry
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.lean', delete=False) as f:
        f.write(test_content)
        test_file = f.name

    try:
        # 测试搜索功能
        print("ℹ️  测试搜索功能...")
        proc = await asyncio.create_subprocess_exec(
            str(exe), "search", test_file, "sorry",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode == 0:
            output = stdout.decode('utf-8', errors='replace')
            if "Found" in output and "match" in output:
                print("✅ 搜索功能正常")
                return True
            else:
                print(f"⚠️  搜索输出异常: {output[:200]}")
                return False
        else:
            print(f"❌ 搜索失败 (exit {proc.returncode})")
            print(f"   stderr: {stderr.decode('utf-8', errors='replace')[:200]}")
            return False

    except asyncio.TimeoutError:
        print("❌ 搜索超时")
        return False
    except Exception as e:
        print(f"❌ 测试出错: {e}")
        return False
    finally:
        Path(test_file).unlink(missing_ok=True)


async def main():
    print("开始测试语法感知代码修改工具...\n")

    results = []
    results.append(("Lean 源文件", test_lean_files_exist()))
    results.append(("lakefile 更新", test_lakefile_updated()))
    results.append(("Python 包装器", test_python_wrapper_exists()))
    results.append(("文档", test_documentation()))

    # 异步测试
    build_result = await test_build_tool()
    results.append(("构建 Lean 工具", build_result))

    if build_result:
        func_result = await test_basic_functionality()
        if func_result is not None:
            results.append(("基本功能", func_result))

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, result in results if result is True)
    skipped = sum(1 for _, result in results if result is None)
    failed = sum(1 for _, result in results if result is False)
    total = len(results)

    for name, result in results:
        if result is True:
            status = "✅ 通过"
        elif result is False:
            status = "❌ 失败"
        else:
            status = "⚠️  跳过"
        print(f"{status} - {name}")

    print(f"\n总计: {passed} 通过, {failed} 失败, {skipped} 跳过 (共 {total} 项)")

    if failed == 0:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print(f"\n⚠️  {failed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
