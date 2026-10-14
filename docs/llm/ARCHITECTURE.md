# 架构

## 包结构

```text
src/
  common/     # 公共基建：config、logger
  api/        # 公共 HTTP 层
  llm/        # 大模型调用
  rag/        # 文档 RAG
```

## 大模型调用分层

```text
CLI → Session → LLMClient → ProtocolAdapter → HttpTransport
                     │                │
                     └─ 使用 common.config / common.logger
```

- **common.config**：`.env` 加载与各域配置（模型、日志等）
- **common.logger**：控制台 / 按大小轮转的文件日志
- **Transport**：httpx 同步/异步请求与 SSE 行迭代
- **ProtocolAdapter**：组请求、解响应、流事件、错误解析
- **LLMClient**：对外统一 API；出站前校验 tools / 消息 / 工具轮次配对
- **tool_helpers**：arguments 解析、finish_reason 完整性、请求校验
- **Session**：维护 `Message[]`，仅成功时追加 assistant（可含 tool_calls）；**不**自动执行工具
- **CLI**：交互与展示；启动时 `setup_logging`

## 扩展点

- 新协议：新增 Adapter + `registry` 注册 + 测试 + [PROTOCOLS.md](PROTOCOLS.md)
- 新配置域：`src/common/config/` 新模块（复用 `load_env`）
- 新公共能力：`src/common/` 新子包 + `docs/common/` 文档
- 统一调用类型见 [UNIFIED_API.md](UNIFIED_API.md)
- 日志细节见 [docs/common/LOGGING.md](../common/LOGGING.md)
