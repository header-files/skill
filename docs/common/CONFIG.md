# 配置

`common.config`（`src/common/config/`）从扁平 `.env`（及同前缀的进程环境变量）加载配置。模板见仓库根目录 [`.env.example`](../../.env.example)。真实 `.env` 含密钥，不提交仓库。

加载约定：

- 先读 `.env` 文件（默认当前目录 `./.env`，可用 `--env-file` 覆盖），再合并匹配前缀的进程环境变量（后者覆盖前者）
- 多实例 id（`MODEL_<ID>_` / `EMBEDDING_<ID>_` / `RERANK_<ID>_`）中的 `<ID>` **仅字母与数字**，大小写不敏感，内部转小写
- 显式调用参数默认透传下游；配置里的未知额外字段进入请求 JSON（见各域说明），不支持时由上游报错，禁止静默丢弃

## 模块

| 模块 | 职责 |
|------|------|
| `common.config.env` | 通用 `.env` 加载（`load_env`） |
| `common.config.errors` | `ConfigError` |
| `common.config.models` | 对话模型 |
| `common.config.embeddings` | Embedding 端点 |
| `common.config.rerank` | Rerank 端点 |
| `common.config.rag` | RAG 流水线（含配置层校验） |
| `common.config.api` | HTTP 监听与 CLI 默认地址 |
| `common.config.log_settings` | 日志 |
| `common.config.endpoints` | Embedding / Rerank 共用多实例加载 |
| `common.config.parsing` | 布尔 / 整数 / 浮点解析 |

---

## 对话模型（`MODEL_*`）

前缀：`MODEL_`；默认选型键：`DEFAULT_MODEL`。

```env
DEFAULT_MODEL=chatgpt
MODEL_CHATGPT_PROTOCOL=openai-completions
MODEL_CHATGPT_NAME=gpt-4o-mini
MODEL_CHATGPT_BASE_URL=https://api.openai.com/v1
MODEL_CHATGPT_API_KEY=sk-xxx
MODEL_CHATGPT_TIMEOUT_SECONDS=60
```

### 全局

| 配置项 | 默认 | 必填 | 说明 | 校验 |
|--------|------|------|------|------|
| `DEFAULT_MODEL` | 第一个加载到的模型 id | 否 | 未指定模型时选用的 id | 必须已在 `MODEL_*` 中定义 |

### 每个实例 `MODEL_<ID>_*`

| 配置项 | 默认 | 必填 | 说明 | 校验 |
|--------|------|------|------|------|
| `PROTOCOL` | `openai-completions` | 否 | 协议 id | 见下表 |
| `NAME` | — | **是** | 上游模型名 | 非空 |
| `BASE_URL` | — | **是** | API 根地址（去尾 `/`） | 非空 |
| `API_KEY` | — | **是** | 鉴权密钥 | 非空；**不写日志** |
| `TIMEOUT_SECONDS` | `60` | 否 | HTTP 超时（秒） | 可解析为 float |
| `ANTHROPIC_VERSION` | `2023-06-01` | 否 | 仅 Anthropic 使用的版本头 | 字符串 |
| 其它 `MODEL_<ID>_<FIELD>` | — | 否 | 进入 `ModelConfig.extra` | 透传；不支持则下游报错 |

支持的 `PROTOCOL`：

| 协议 id | 说明 | 缺省 |
|---------|------|------|
| `openai-completions` | OpenAI Chat Completions | 是 |
| `openai-responses` | OpenAI Responses API | |
| `anthropic-messages` | Anthropic Messages | |

选型：`RAG_CHAT_MODEL` / `RAG_QUERY_REWRITE_MODEL` 为空时，分别回落到 `DEFAULT_MODEL`。

---

## Embedding（`EMBEDDING_*`）

前缀：`EMBEDDING_`；默认选型键：`DEFAULT_EMBEDDING`。

```env
DEFAULT_EMBEDDING=bge
EMBEDDING_BGE_PROTOCOL=openai-embeddings
EMBEDDING_BGE_NAME=text-embedding-v4
EMBEDDING_BGE_BASE_URL=https://example.com/compatible-mode/v1
EMBEDDING_BGE_API_KEY=sk-xxx
EMBEDDING_BGE_TIMEOUT_SECONDS=60
EMBEDDING_BGE_DIMENSIONS=1024
EMBEDDING_BGE_ENCODING_FORMAT=float
```

### 全局

| 配置项 | 默认 | 必填 | 说明 | 校验 |
|--------|------|------|------|------|
| `DEFAULT_EMBEDDING` | 第一个 Embedding id | 否 | 未指定时选用的 id | 必须已定义 |

### 每个实例 `EMBEDDING_<ID>_*`

| 配置项 | 默认 | 必填 | 说明 | 校验 |
|--------|------|------|------|------|
| `PROTOCOL` | `openai-embeddings` | 否 | 协议 id | 见下表 |
| `NAME` | — | **是** | 上游模型名 | 非空 |
| `BASE_URL` | — | **是** | 根地址或已含 `/embeddings` 的完整 URL | 非空；去尾 `/` |
| `API_KEY` | — | **是** | 鉴权密钥 | 非空；**不写日志** |
| `TIMEOUT_SECONDS` | `60` | 否 | HTTP 超时（秒） | `> 0` |
| `DIMENSIONS` | — | 否 | 向量维度，以**整数**写入请求 JSON | 正整数 |
| 其它字段（如 `ENCODING_FORMAT`） | — | 否 | 进入请求 JSON 顶层（字符串） | 透传 |

支持的 `PROTOCOL`（本期）：

| 协议 id | 缺省 | 请求 | 说明 |
|---------|------|------|------|
| `openai-embeddings` | 是 | `POST {base}/embeddings` | body：`model`、`input`；响应：`data[].embedding`。`BASE_URL` 已以 `/embeddings` 结尾则不再拼接 |

`RAG_EMBEDDING_MODEL` 为空时用 `DEFAULT_EMBEDDING`。

百炼等兼容入口示例：把 `BASE_URL` 设为 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`（或带 `/embeddings` 的完整路径），`NAME=text-embedding-v4`，按需加 `ENCODING_FORMAT=float`、`DIMENSIONS=1024`。原生 `.../services/embeddings/text-embedding/text-embedding` **不在**本期协议内。

---

## Rerank（`RERANK_*`）

前缀：`RERANK_`；默认选型键：`DEFAULT_RERANK`。

```env
DEFAULT_RERANK=cohere
RERANK_COHERE_PROTOCOL=cohere-rerank
RERANK_COHERE_NAME=rerank-v3.5
RERANK_COHERE_BASE_URL=https://api.example.com/v1
RERANK_COHERE_API_KEY=sk-xxx
RERANK_COHERE_TIMEOUT_SECONDS=60
```

### 全局

| 配置项 | 默认 | 必填 | 说明 | 校验 |
|--------|------|------|------|------|
| `DEFAULT_RERANK` | 第一个 Rerank id | 否 | 未指定时选用的 id | 必须已定义 |

### 每个实例 `RERANK_<ID>_*`

| 配置项 | 默认 | 必填 | 说明 | 校验 |
|--------|------|------|------|------|
| `PROTOCOL` | `cohere-rerank` | 否 | 协议 id | 见下表 |
| `NAME` | — | **是** | 上游模型名 | 非空 |
| `BASE_URL` | — | **是** | 根地址或协议约定的完整路径 | 非空；去尾 `/` |
| `API_KEY` | — | **是** | 鉴权密钥 | 非空；**不写日志** |
| `TIMEOUT_SECONDS` | `60` | 否 | HTTP 超时（秒） | `> 0` |
| 其它字段（如 `INSTRUCT`） | — | 否 | 按协议进入请求体 | 见下表 |

支持的 `PROTOCOL`：

| 协议 id | 缺省 | 请求 | 响应 | 额外字段去向 |
|---------|------|------|------|----------------|
| `cohere-rerank` | 是 | `POST {base}/rerank`；顶层 `model` / `query` / `documents` / `top_n` | 顶层 `results[]`（或 `data[]`）的 `index`、`relevance_score` | 请求 JSON **顶层** |
| `dashscope-text-rerank` | | `POST {base}/services/rerank/text-rerank/text-rerank`；`model` + `input.{query,documents}` + `parameters.{top_n,...}` | `output.results[]` | 进入 **`parameters`**（如 `INSTRUCT`） |

`BASE_URL`：`cohere-rerank` 可写到服务根或已含 `/rerank`；`dashscope-text-rerank` 可写到 `/api/v1`，或写到以 `/text-rerank` 结尾的完整 URL。  
运行时显式传入的 `top_n` 覆盖配置里的同名项。  
`RAG_RERANK_MODEL` 为空时用 `DEFAULT_RERANK`。`RAG_RERANK_ENABLED=false` 时不加载 Rerank 端点。

百炼示例：

```env
DEFAULT_RERANK=qwen
RERANK_QWEN_PROTOCOL=dashscope-text-rerank
RERANK_QWEN_NAME=qwen3.7-text-rerank
RERANK_QWEN_BASE_URL=https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1
RERANK_QWEN_API_KEY=sk-xxx
# RERANK_QWEN_INSTRUCT=Given a web search query, retrieve relevant passages that answer the query.
```

---

## RAG 流水线（`RAG_*`）

由 `load_rag_settings` 加载；非法组合在启动/加载时抛 `ConfigError`。

```env
RAG_CHAT_MODEL=chatgpt
RAG_EMBEDDING_MODEL=bge
RAG_RERANK_MODEL=cohere
RAG_RERANK_ENABLED=true
RAG_VECTOR_STORE=faiss
RAG_CHUNK_SIZE=800
RAG_CHUNK_OVERLAP=120
RAG_CHUNK_SEPARATORS=
RAG_EMBED_BATCH_SIZE=16
RAG_RETRIEVE_TOP_K=20
RAG_RERANK_TOP_N=5
RAG_QUERY_REWRITE_ENABLED=false
RAG_QUERY_REWRITE_MODEL=
RAG_QUERY_REWRITE_PROMPT=
RAG_MAX_CONTEXT_CHARS=12000
RAG_MAX_HISTORY_TURNS=10
RAG_MAX_UPLOAD_BYTES=20971520
RAG_SYSTEM_PROMPT=
```

### 全量表

| 配置项 | 默认 | 必填 | 说明 | 校验 |
|--------|------|------|------|------|
| `RAG_CHAT_MODEL` | 空 → `DEFAULT_MODEL` | 否 | 问答所用对话模型 id | 须为已配置的 `MODEL_*` id |
| `RAG_EMBEDDING_MODEL` | 空 → `DEFAULT_EMBEDDING` | 否 | 向量化所用 Embedding id | 须为已配置的 `EMBEDDING_*` id |
| `RAG_RERANK_MODEL` | 空 → `DEFAULT_RERANK` | 否 | 重排所用 Rerank id；仅 `RAG_RERANK_ENABLED=true` 时加载 | 须为已配置的 `RERANK_*` id |
| `RAG_RERANK_ENABLED` | `true` | 否 | 是否启用重排 | 布尔。为 `true` 时一次问答通常含 Embedding + Rerank + LLM（改写开启时还可能多一次） |
| `RAG_VECTOR_STORE` | `faiss` | 否 | 向量库种类 | 本期仅 `faiss`；进程内、**不落盘**，随 `rag serve` 重启清空 |
| `RAG_CHUNK_SIZE` | `800` | 否 | 切分目标长度（字符） | `>= 1` |
| `RAG_CHUNK_OVERLAP` | `120` | 否 | 相邻 chunk 重叠字符数 | `>= 0` 且 **`< RAG_CHUNK_SIZE`** |
| `RAG_CHUNK_SEPARATORS` | 内置默认 | 否 | 递归切分分隔符列表 | 用 `\|` 分隔；支持 `\n` `\t` `\r` 转义。未设置时用：`\n\n`、`\n`、`。`、`！`、`？`、`. `、空格、最后按字符切开。设为空字符串会得到「仅空分隔符」行为，与「未设置」不同 |
| `RAG_EMBED_BATCH_SIZE` | `16` | 否 | 入库 / 检索侧 Embedding 批大小 | `>= 1` |
| `RAG_RETRIEVE_TOP_K` | `20` | 否 | 向量召回最终条数 | `>= 1` |
| `RAG_RERANK_TOP_N` | `5` | 否 | 重排保留条数 | `>= 1` 且 **`<= RAG_RETRIEVE_TOP_K`** |
| `RAG_QUERY_REWRITE_ENABLED` | `false` | 否 | 是否开启检索前 Query 改写 | 布尔。默认关 |
| `RAG_QUERY_REWRITE_MODEL` | 空 → 复用问答模型 | 否 | 改写用对话模型 id | 开启改写时有效；空则用 `RAG_CHAT_MODEL` / `DEFAULT_MODEL` |
| `RAG_QUERY_REWRITE_PROMPT` | 内置改写提示 | 否 | 改写系统提示 | 空则用内置默认。无会话历史时跳过改写调用；失败或空输出回退原问题。Session / Context 仍用用户原文 |
| `RAG_MAX_CONTEXT_CHARS` | `12000` | 否 | 本轮塞进 Prompt 的资料字符上限 | `>= 1`。**字符近似**，非精确 token |
| `RAG_MAX_HISTORY_TURNS` | `10` | 否 | 多轮历史保留的「轮」数（一轮 = user+assistant） | `>= 0`；`0` 表示不保留历史 |
| `RAG_MAX_UPLOAD_BYTES` | `20971520`（20MiB） | 否 | 单文件上传上限 | `>= 1` |
| `RAG_SYSTEM_PROMPT` | 内置知识库助手提示 | 否 | 问答 system 内容 | 空则用内置默认 |

布尔取值（适用所有 `*_ENABLED` 等）：`true`/`false`、`1`/`0`、`yes`/`no`、`on`/`off`（大小写不敏感）。

---

## Skill Runtime（`SKILL_*`）

| 配置项 | 默认 | 必填 | 说明 | 校验 |
|--------|------|------|------|------|
| `SKILL_ROOTS` | 空 | 否 | Skill 根目录列表 | 用 `:` 分隔；每个根下一层子目录为候选 Skill |
| `SKILL_CHAT_MODEL` | 空 → `DEFAULT_MODEL` | 否 | 执行 Skill 所用对话模型 id | 须为已配置的 `MODEL_*` |
| `SKILL_FINGERPRINT_MODE` | `content` | 否 | 目录指纹模式 | `content`（默认，内容哈希）或 `meta`（有漏检风险） |
| `SKILL_SCRIPT_TIMEOUT_SECONDS` | `30` | 否 | 单脚本超时 | `>= 0.1` |
| `SKILL_SCRIPT_MAX_CONCURRENT` | `4` | 否 | 全局脚本并发上限 | `>= 1` |
| `SKILL_SCRIPT_MAX_OUTPUT_BYTES` | `1048576` | 否 | stdout+stderr 合计缓冲上限 | `>= 1` |
| `SKILL_AGENT_MAX_STEPS` | `20` | 否 | Agent 最大步数 | `>= 1` |
| `SKILL_AGENT_TIMEOUT_SECONDS` | `300` | 否 | 整次 run 超时 | `>= 0.1` |
| `SKILL_READ_MAX_BYTES` | `1048576` | 否 | `read_resource` 上限 | `>= 1` |

---

## 公共 HTTP（`API_*`）

供 `rag serve` 监听与 CLI 默认连址。

| 配置项 | 默认 | 必填 | 说明 | 校验 |
|--------|------|------|------|------|
| `API_HOST` | `127.0.0.1` | 否 | 服务绑定地址 | 非空字符串 |
| `API_PORT` | `8000` | 否 | 服务端口 | `1..65535` |
| `API_BASE_URL` | `http://{API_HOST}:{API_PORT}` | 否 | CLI 默认 API 根 URL（去尾 `/`） | 非空；`--base-url` 可覆盖 |
| `API_TIMEOUT_SECONDS` | `120` | 否 | CLI HTTP 超时（秒） | `>= 0.1` |

---

## 日志（`LOG_*`）

详行为见 [LOGGING.md](LOGGING.md)。项一览：

| 配置项 | 默认 | 必填 | 说明 | 校验 |
|--------|------|------|------|------|
| `LOG_LEVEL` | `INFO` | 否 | 日志级别 | `CRITICAL` / `ERROR` / `WARNING` / `INFO` / `DEBUG` / `NOTSET` |
| `LOG_TO_CONSOLE` | `true` | 否 | 是否输出到 stderr | 布尔 |
| `LOG_TO_FILE` | `false` | 否 | 是否写文件 | 布尔 |
| `LOG_FILE_PATH` | `logs/app.log` | 否 | 日志文件路径 | 路径字符串 |
| `LOG_MAX_BYTES` | `10485760`（10MiB） | 否 | 单文件大小上限，超出轮转 | `>= 0`；`LOG_TO_FILE=true` 时须 `> 0` |
| `LOG_BACKUP_COUNT` | `5` | 否 | 轮转保留份数 | `>= 0` |
| `LOG_FORMAT` | 含 `%(trace_id)s` 的默认格式 | 否 | `logging` 格式串 | 非空 |
| `LOG_ENSURE_FIELDS` | `trace_id` | 否 | 未绑定时填 `-` 的字段列表 | 逗号分隔，至少一个字段 |

---

## 加载 API

```python
from common.config import (
    ConfigError,
    get_embedding,
    get_model,
    get_reranker,
    load_api_settings,
    load_embeddings,
    load_log_settings,
    load_models,
    load_rag_settings,
    load_rerankers,
)
```

典型入口：`rag serve` / `rag` CLI 在启动时 `setup_logging` + 加载上述配置；业务运行时通过 `RagRuntime.from_env` 组装。
