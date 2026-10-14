# 需求说明

## 目标

实现可扩展的大模型调用能力：自研 HTTP 层、统一抽象、多模型配置、可配置日志、CLI 对话、Tool Calling。

## 功能需求

1. Python + uv 依赖管理
2. 公共配置：扁平 `.env`；密钥等敏感项本地存放、不进仓库；配置加载落在 `common.config`
3. 公共日志：支持控制台与本地文件；文件按大小轮转（超限新增文件）；可用配置开关各输出目标；落在 `common.logger`
4. 协议：`openai-completions`（默认）、`openai-responses`、`anthropic-messages`
5. 同步/异步，流式/非流式；基于 httpx，不使用官方 SDK
6. 分层设计，便于扩展新基模协议
7. CLI 客户端，拼接多轮上下文；无前端
8. 响应侧支持 Reasoning 文本事件流
9. 上游错误归一为统一 Error
10. Tool Calling：统一 ToolSpec / ToolCall；三协议非流式与流式；出站校验与工具轮次配对
11. 保留文档（人读 README + agent 可读 docs）
12. 开发过程编写单元测试

## 非目标（第一期）

- 前端 / 对外 HTTP API 服务（llm 域本身）
- 多模态
- 自动执行工具的 Agent 循环（由上层如 Skill Runtime 负责）
