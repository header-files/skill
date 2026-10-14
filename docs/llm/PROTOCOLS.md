# 协议说明

## openai-completions

- URL：`{base_url}/chat/completions`（base 已含完整路径则直接用）
- `max_output_tokens` → `max_tokens`
- 流式：SSE `data:`；`[DONE]` 结束
- reasoning：`message/delta.reasoning_content` 或 `reasoning`
- tools：`tools[].type=function`；`tool_choice` 字符串
- 历史：assistant `tool_calls`；结果 `role=tool` + `tool_call_id`
- 流式 tool：按 `tool_calls[].index` 累积 arguments 字符串，结束后再解析

## openai-responses

- URL：`{base_url}/responses`
- system → `instructions`；其余 → `input`
- `max_output_tokens` 原样发送
- 流式事件：`response.output_text.delta`、`response.reasoning_text.delta` 等
- tools：function tools；历史 `function_call` / `function_call_output`
- **`ToolCall.id` = `call_id`**（不用 output item 的 `id`）
- **`function_call.arguments` wire 必须为 JSON 字符串**（禁止传 dict）
- 流式：按 call_id / index 累积，完成后解析；验收与另外两协议同级

## anthropic-messages

- URL：`{base}/v1/messages`（base 以 `/v1` 结尾则只拼 `/messages`）
- Header：`x-api-key`、`anthropic-version`
- system 独立字段；`max_output_tokens` → `max_tokens`（缺省 4096）
- thinking 块 → reasoning 事件/字段
- tools：`name` / `description` / `input_schema`；`tool_choice`：`auto` / `none` / `required`→`any`
- 无有效 tools 且 choice 为 null/none：**不传 tools、不传 tool_choice**
- 有 tools + none：传 tools + `{"type":"none"}`
- 结果：统一 `role=tool` → user 消息内 `tool_result`（相邻 tool 合并）
- 流式：按 `content_block` 索引累积 `input_json_delta`，`content_block_stop` 后再 parse；支持多 tool 交错

## 新增协议

实现 `ProtocolAdapter`，在 `registry.py` 注册，补充测试与本文档。
