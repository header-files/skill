# Skill Runtime 需求

## 目标

在本地发现、加载并以 LLM + 三工具方式执行 Skill（`SKILL.md` 目录）。调用方指定 Skill；Runtime 不负责选型。

## 功能

1. 从 `SKILL_ROOTS` 发现 Skill（名称、描述、目录）；非法项记入错误且不阻断其它
2. 同名冲突全部排除
3. 按名加载：元信息、完整说明、资源清单（按需读内容）
4. 执行：复用 `llm` Tool Calling；工具限 `list_resources` / `read_resource` / `run_script`
5. 路径沙箱；脚本 async 子进程、超时杀进程组、输出合计上限、并发上限
6. 默认 content 指纹；跨调用新鲜度；单次 run 入口快照语义
7. CLI：`list` / `inspect` / `run`
8. 单元测试覆盖关键路径

## 非目标

- Skill HTTP API
- OS 级执行沙箱（网络/宿主机隔离）
- 单次 run 内 copy 内容快照
- 自动选择应使用哪个 Skill
