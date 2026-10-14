# Agent 指南

换机器或新会话时，先读本文件，再按需深入 `docs/common/`、`docs/llm/`、`docs/skill/` 与 `docs/rag/`。

## 项目是什么

Python + uv：公共基建（配置、日志）+ 多协议 LLM（含 Tool Calling）+ **本地 Skill Runtime** + 文档 RAG（FAISS、Embedding、Rerank、多轮会话）+ 公共 HTTP 层（`src/api`，本期无 Skill HTTP）。

## 技术栈

- Python >= 3.11，uv
- httpx、FastAPI、uvicorn、typer、PyYAML、faiss-cpu、numpy、python-docx、pypdf
- 测试：pytest、respx

## 目录地图

```text
src/common/     config / logger（含 SKILL_*）
src/api/        公共 HTTP（本期不挂 skill）
src/llm/        对话客户端与 Tool Calling
src/skill/      Skill Runtime 与 skill CLI
src/rag/        RAG 流水线与 cli
docs/
tests/
.env.example
```

## 必读顺序

1. `docs/common/CONFIG.md` / `LOGGING.md`
2. `docs/skill/REQUIREMENTS.md` / `ARCHITECTURE.md` / `CLI.md`
3. `docs/llm/UNIFIED_API.md`（Tool Calling）
4. 改 RAG 时读 `docs/rag/`

## 常用命令

```bash
uv sync
uv run pytest
uv run skill list --skills-dir ./skills
uv run skill inspect NAME --skills-dir ./skills
uv run skill run NAME --task "..." --skills-dir ./skills
uv run rag serve
```

## Git

- 远程：`git@github.com:header-files/skill.git`
- 主分支：`main`
- Conventional Commits
