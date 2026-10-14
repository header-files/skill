# 错误处理

## 配置错误

配置加载或校验失败时抛出 `common.config.errors.ConfigError`。

## 上游 / 调用错误流程

上游非 2xx / 流错误 → Transport 提供 status+body → Adapter 解析 → 统一 `LLMError` → 调用方。

## LLMError

```text
type: auth_error | api_error | timeout_error
    | network_error | stream_error | unsupported_parameter
    | invalid_request
message: string
status_code: int | null
provider_code: string | null
retryable: bool | null
```

配置问题使用 `ConfigError`；调用链路问题使用 `LLMError`。

## 归类

| 情况 | 类型 |
|------|------|
| 配置缺失/非法 | `ConfigError` |
| 401/403 | auth_error |
| 超时 | timeout_error |
| 连接失败 | network_error |
| 流中断/解析失败 | stream_error |
| 可识别参数不支持 | unsupported_parameter |
| 本地请求非法（tools/消息/工具轮次配对等） | invalid_request |
| 其他上游错误 | api_error |

`message` 优先取厂商错误文案；不回显 API Key。
