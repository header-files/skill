# 客户端交互协议（统一抽象）

调用方只认本节类型。

## Message

```text
role: "system" | "user" | "assistant" | "tool"
content: string | null
tool_calls: ToolCall[] | null   # 仅 assistant
tool_call_id: string | null     # 仅 tool，对应 ToolCall.id
name: string | null             # 可选
```

- system / user：`content` 必为 string；不得带 tool_calls / tool_call_id
- assistant：`content` 与 `tool_calls` 至少一个有意义；有 tool_calls 时每项 id/name 非空，同消息内 id 不重复；`tool_calls: []` 正规化为 null
- tool：`tool_call_id` 非空；`content` 为 string（可 `""`）

## ToolSpec / ToolCall

```text
ToolSpec
  name: string
  description: string
  parameters: object          # JSON Schema

ToolCall
  id: string                  # 工具调用关联 ID
  name: string
  arguments_raw: string
  arguments: object | null    # 仅完整且解析为 JSON object 时非 null
  arguments_parse_error: string | null
  truncated: bool
```

禁止用 `{}` 顶替解析失败。合法空对象 `{}` 与解析失败可区分。

### 执行前置（上层硬约束）

`llm` 不执行工具。执行前必须：`truncated == false`、`arguments is not null`、按对应 ToolSpec 做 JSON Schema 校验通过；否则禁止执行。

### 关联 ID

| 协议 | ToolCall.id | 结果字段 |
|------|-------------|---------|
| openai-completions | tool_calls[].id | tool_call_id |
| openai-responses | **function_call.call_id**（非 item id） | function_call_output.call_id |
| anthropic-messages | tool_use.id | tool_result.tool_use_id |

## ChatRequest

```text
messages: Message[]
temperature: float | null
max_output_tokens: int | null
stop: string[] | null
tools: ToolSpec[] | null
tool_choice: "auto" | "none" | "required" | null
```

- `null` 字段不发送
- 无有效 tools（`null` 或 `[]`）且 `tool_choice` 为 `null` 或 `"none"`：合法；wire 省略 `tools` 与 `tool_choice`
- 无有效 tools 且 `tool_choice` 为 `auto` / `required`：`invalid_request`
- 出站前做消息校验与**工具轮次严格配对**：每个 assistant.tool_calls 的每个 id 在结果区恰好一条 tool 结果；禁重复、禁遗漏后继续请求

## ChatResponse

```text
content: string
reasoning: string | null
tool_calls: ToolCall[] | null
finish_reason: FinishReason | null
model: string | null
usage: Usage | null
```

`FinishReason` 在现有取值上**增量**增加 `"tool_calls"`（保留 `stop` / `length` / `content_filter` 等）。不含厂商 `raw`。

完整性：截断且存在不完整 tool 时优先保留截断类 finish_reason，禁止「列表非空就无条件标为 tool_calls」。

## StreamChunk

```text
type: "reasoning" | "content" | "finish"
delta: string
finish_reason: FinishReason | null
model: string | null
usage: Usage | null
tool_calls: ToolCall[] | null   # 仅 finish 可非空
```

- 成功结束时有且仅有一次 `finish`
- 纯 tool、无文本也必须发 `finish`
- 纯文本无 tools 行为与旧版一致
- 工具参数在 Adapter 内按 call/block 索引先拼 `arguments_raw`，完成后再解析（Anthropic：`input_json_delta` 按 content_block 索引累积）

## Error

见 `ERRORS.md`（含 `invalid_request`）。

## Client API

```text
chat / chat_stream / achat / achat_stream
LLMClient.from_env(model_id?)
```

出站前 `validate_chat_request`。Session / CLI **不**自动执行工具。
