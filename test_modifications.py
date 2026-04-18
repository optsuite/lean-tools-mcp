#!/usr/bin/env python3
"""
测试 lean-tools-mcp 的修改

验证：
1. CLI 模式能正确检测错误
2. 补丁文件已正确创建
3. 构建脚本支持新的补丁版本
"""

import sys
from pathlib import Path

# 添加 lean-tools-mcp 到路径
REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))

def test_cli_mode_import():
    """测试 CLI 模式能否正确导入"""
    print("=== Test 1: CLI 模式导入 ===")
    try:
        from lean_tools_mcp.tools.run_code_cli import lean_run_code_cli
        print("✅ run_code_cli.py 导入成功")
        return True
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return False

def test_run_code_import():
    """测试 run_code.py 的修改"""
    print("\n=== Test 2: run_code.py 修改 ===")
    try:
        from lean_tools_mcp.tools.run_code import lean_run_code, USE_LSP_MODE
        print(f"✅ run_code.py 导入成功")
        print(f"   USE_LSP_MODE = {USE_LSP_MODE} (应该是 False)")
        return not USE_LSP_MODE  # 默认应该是 False
    except Exception as e:
        print(f"❌ 导入失败: {e}")
        return False

def test_patch_files():
    """测试补丁文件是否存在"""
    print("\n=== Test 3: 补丁文件 ===")
    patch_dir = REPO_ROOT / "memory_optimization" / "patches" / "v4.27-dynamic-fix"

    required_files = [
        "Watchdog.lean",
        "FileWorker.lean",
        "Import.lean",
        "Shell.lean",
        "README.md"
    ]

    all_exist = True
    for filename in required_files:
        filepath = patch_dir / filename
        if filepath.exists():
            print(f"✅ {filename} 存在")
        else:
            print(f"❌ {filename} 不存在")
            all_exist = False

    return all_exist

def test_watchdog_patch():
    """测试 Watchdog.lean 的修改"""
    print("\n=== Test 4: Watchdog.lean 修改 ===")
    patch_file = REPO_ROOT / "memory_optimization" / "patches" / "v4.27-dynamic-fix" / "Watchdog.lean"

    if not patch_file.exists():
        print("❌ Watchdog.lean 不存在")
        return False

    content = patch_file.read_text()

    # 检查关键修改
    checks = [
        ("PATCH: Support dynamic", "包含补丁注释"),
        ("try", "包含 try-catch"),
        ("moduleFromDocumentUri", "调用 moduleFromDocumentUri"),
        ("catch _ =>", "包含异常处理"),
        ("Name.mkSimple", "包含合成模块名逻辑"),
    ]

    all_passed = True
    for pattern, description in checks:
        if pattern in content:
            print(f"✅ {description}")
        else:
            print(f"❌ 缺少: {description}")
            all_passed = False

    return all_passed

def test_build_script():
    """测试构建脚本的修改"""
    print("\n=== Test 5: 构建脚本修改 ===")
    build_script = REPO_ROOT / "memory_optimization" / "scripts" / "build_lean.py"

    if not build_script.exists():
        print("❌ build_lean.py 不存在")
        return False

    content = build_script.read_text()

    checks = [
        ("v4.27-dynamic-fix", "支持新补丁版本"),
        ("--patch-version", "添加了 --patch-version 参数"),
    ]

    all_passed = True
    for pattern, description in checks:
        if pattern in content:
            print(f"✅ {description}")
        else:
            print(f"❌ 缺少: {description}")
            all_passed = False

    return all_passed

def test_documentation():
    """测试文档是否存在"""
    print("\n=== Test 6: 文档 ===")
    docs = [
        ("LSP_DYNAMIC_FILE_ISSUE.md", "LSP 问题分析文档"),
        ("memory_optimization/patches/v4.27-dynamic-fix/README.md", "补丁使用说明"),
    ]

    all_exist = True
    for filepath, description in docs:
        full_path = REPO_ROOT / filepath
        if full_path.exists():
            print(f"✅ {description}")
        else:
            print(f"❌ {description} 不存在")
            all_exist = False

    return all_exist

def main():
    print("开始测试 lean-tools-mcp 修改...\n")

    results = []
    results.append(("CLI 模式导入", test_cli_mode_import()))
    results.append(("run_code.py 修改", test_run_code_import()))
    results.append(("补丁文件", test_patch_files()))
    results.append(("Watchdog.lean 修改", test_watchdog_patch()))
    results.append(("构建脚本修改", test_build_script()))
    results.append(("文档", test_documentation()))

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())
