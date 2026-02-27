# Phase 2 Mathlib 内存实测 & MCP 适配 (2026-02-27)

## 概述

在 Phase 2（in-process worker）完成后，进行了完整的 Mathlib 内存实测，并将 in-process worker 模式集成到 MCP 工具链中。

## 1. Lean 4 修改回移到 v4.29.0-rc2

由于我们的修改版 lean（v4.30.0-pre）与当前 Mathlib（目标 v4.29.0-rc2）不兼容，将 Phase 2 的所有修改回移到 v4.29.0-rc2：

- 克隆 `lean4` 仓库 `v4.29.0-rc2` 标签到 `lean4-v429/`
- 复制修改后的文件：`Watchdog.lean`、`FileWorker.lean`、`ChannelStream.lean`、`Import.lean`、`Shell.lean`
- 编译成功（约 10 分钟），版本号：`Lean (version 4.29.0, commit 83e54b65)`
- 使用 `lake exe cache get` 下载 Mathlib 预构建缓存（8021 文件）

## 2. 内存实测结果

### 2.1 `import Mathlib.Tactic`（每个 worker ~2.8 GB）

#### 3 文件对比

| 指标 | Process 模式 | In-process 模式 | 节省 |
|------|------------|----------------|------|
| 总进程数 | 4 (1 Watchdog + 3 Worker) | **1** | 75% |
| 总内存 | **8,399 MB** (8.2 GB) | **2,920 MB** (2.9 GB) | **65.2%** |
| File 0 增长 | +2,782 MB | +2,883 MB | ~相同 |
| File 1 增长 | +2,806 MB | **-152 MB** (GC) | **100%+** |
| File 2 增长 | +2,764 MB | **+12 MB** | **99.6%** |

#### 5 文件对比

| 指标 | Process 模式 | In-process 模式 | 节省 |
|------|------------|----------------|------|
| 总进程数 | 6 | **1** | 83% |
| 总内存 | **13,640 MB** (13.3 GB) | **2,846 MB** (2.8 GB) | **79.1%** |
| File 0 增长 | +2,949 MB | +2,751 MB | ~相同 |
| File 1 增长 | +2,598 MB | **-38 MB** | **100%** |
| File 2 增长 | +2,756 MB | **-41 MB** | **100%** |
| File 3 增长 | +2,721 MB | **-15 MB** | **100%** |
| File 4 增长 | +2,524 MB | **+5 MB** | **99.8%** |

### 2.2 `import Lean`（每个 worker ~1.1 GB）— 5 文件

| 指标 | Process 模式 | In-process 模式 | 节省 |
|------|------------|----------------|------|
| 总内存 | 5,852 MB | 1,362 MB | **76.7%** |
| 每额外文件 | ~1,114 MB | ~3.8 MB | **99.7%** |

### 2.3 `import Init`（每个 worker ~347 MB）— 5 文件

| 指标 | Process 模式 | In-process 模式 | 节省 |
|------|------------|----------------|------|
| 总内存 | 2,019 MB | 593 MB | **70.6%** |
| 每额外文件 | ~347 MB | ~2.8 MB | **99.2%** |

### 2.4 节省比例趋势

| Import 类型 | 单 Worker 大小 | 总内存节省 (5 文件) | 每额外文件节省 |
|------------|--------------|-------------------|-------------|
| Init | 347 MB | 70.6% | 99.2% |
| Lean | 1,113 MB | 76.7% | 99.7% |
| **Mathlib.Tactic** | **2,768 MB** | **79.1%** | **99.8%** |

**结论：Import 越重，节省越显著。Mathlib 场景下 5 文件从 13.6 GB 降到 2.8 GB。**

## 3. MCP 工具链适配

### 3.1 配置层 (`config.py`)

新增 `LSPConfig.use_inprocess_workers` 配置项：
- 环境变量：`LEAN_WORKER_INPROCESS=1`
- 默认关闭（`False`）

### 3.2 客户端层 (`client.py`)

`LSPClient.__init__` 新增 `use_inprocess_workers` 参数。在 `start()` 方法中，若启用则向 lean 子进程传递 `LEAN_WORKER_INPROCESS=1` 环境变量。

### 3.3 连接池层 (`pool.py`)

`LSPPool.__init__` 新增 `use_inprocess_workers` 参数，透传给每个 `LSPClient`。

### 3.4 服务器层 (`server.py`)

- `create_server()` 从 `config.lsp.use_inprocess_workers` 读取配置传给 `LSPPool`
- CLI 新增 `--inprocess` 选项

### 3.5 使用方式

```bash
# 方式 1: 命令行参数
lean-tools-mcp --project-root ~/my-lean-project --inprocess

# 方式 2: 环境变量
LEAN_WORKER_INPROCESS=1 lean-tools-mcp --project-root ~/my-lean-project

# 方式 3: Cursor MCP 配置
{
  "mcpServers": {
    "lean-tools": {
      "command": "lean-tools-mcp",
      "args": ["--project-root", "/path/to/project", "--inprocess"]
    }
  }
}
```

### 3.6 测试

新增 3 个配置测试：
- `test_inprocess_default_off` — 默认关闭
- `test_env_inprocess_workers` — `LEAN_WORKER_INPROCESS=1` 启用
- `test_env_inprocess_workers_off` — `LEAN_WORKER_INPROCESS=0` 不启用

全部 54 个测试通过。

## 4. Benchmark 脚本改进 (`scripts/bench_memory.py`)

- 新增 `--import-name` 参数，支持自定义 import（如 `Lean`、`Mathlib.Tactic`）
- 添加 `flush=True` 强制刷新输出缓冲
- 等待 elaboration 时每 10 秒打印内存进度
- 打印当前正在打开的文件名

## 5. 文件变更清单

### MCP Python 项目
| 文件 | 变更 |
|------|------|
| `src/lean_tools_mcp/config.py` | 新增 `use_inprocess_workers` 配置 |
| `src/lean_tools_mcp/lsp/client.py` | 启动时传递 `LEAN_WORKER_INPROCESS` env |
| `src/lean_tools_mcp/lsp/pool.py` | 透传 `use_inprocess_workers` |
| `src/lean_tools_mcp/server.py` | 新增 `--inprocess` CLI；透传到 LSPPool |
| `tests/test_config.py` | 新增 3 个 inprocess 配置测试 |
| `scripts/bench_memory.py` | 支持 `--import-name`、进度输出、flush |

### Lean 4 修改版 (lean4-v429/)
| 文件 | 变更 |
|------|------|
| `src/Lean/Server/ChannelStream.lean` | 新增：Channel ↔ Stream 适配器 |
| `src/Lean/Server/FileWorker.lean` | try-catch 防崩溃 + per-worker importsLoadedRef |
| `src/Lean/Server/Watchdog.lean` | WorkerHandle + in-process spawning + mode switch |
| `src/Lean/Elab/Import.lean` | Environment 缓存（共享 imported env） |
| `src/Lean/Shell.lean` | 透传 leanOpts 到 watchdogMain |

### Benchmark 结果文件
| 文件 | 内容 |
|------|------|
| `docs/bench_memory_mathlib_process.json` | Mathlib 3 文件 process 模式 |
| `docs/bench_memory_mathlib_inprocess.json` | Mathlib 3 文件 in-process 模式 |
| `docs/bench_memory_mathlib5_process.json` | Mathlib 5 文件 process 模式 |
| `docs/bench_memory_mathlib5_inprocess.json` | Mathlib 5 文件 in-process 模式 |
| `docs/bench_memory_lean5_process.json` | import Lean 5 文件 process 模式 |
| `docs/bench_memory_lean5_inprocess.json` | import Lean 5 文件 in-process 模式 |

## 6. 已知限制

1. **需要修改版 lean**：in-process 模式仅在包含 Phase 2 修改的 lean 二进制文件上生效
2. **版本兼容性**：当前回移到 v4.29.0-rc2，需随 Mathlib 版本更新同步
3. **并发安全**：in-process 模式下所有 worker 共享同一进程，`IO.Process.forceExit` 等 API 已处理，但极端情况下仍需注意
