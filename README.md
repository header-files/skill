# skill

本地 **Skill Runtime**（发现 / 加载 / LLM+三工具执行），并保留多协议 LLM 客户端与文档 RAG。

## 能力

| 域 | 说明 |
|------|------|
| skill | `SKILL.md` 发现与执行；CLI：`skill list/inspect/run` |
| llm | 多协议对话（含 Tool Calling） |
| rag | FAISS 检索、Rerank、多轮会话与 HTTP API |

## 快速开始（Skill）

```bash
uv sync
cp .env.example .env
# 配置 MODEL_* 与 SKILL_ROOTS / SKILL_CHAT_MODEL

uv run skill list --skills-dir ./path/to/skills-root
uv run skill inspect demo-skill --skills-dir ./path/to/skills-root
uv run skill run demo-skill --task "..." --skills-dir ./path/to/skills-root
```

## RAG（保留）

```bash
uv run rag serve
uv run rag upload ./notes.md
uv run rag chat
```

## 文档

| 文档 | 说明 |
|------|------|
| [docs/AGENT.md](docs/AGENT.md) | Agent 地图 |
| [docs/common/](docs/common/) | 配置与日志 |
| [docs/llm/](docs/llm/) | 对话与 Tool Calling |
| [docs/skill/](docs/skill/) | Skill Runtime |
| [docs/rag/](docs/rag/) | RAG |

```bash
uv run pytest
```
