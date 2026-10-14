# Skill Runtime 架构

## 信任模型

Skill 与用户放入根目录的本地代码同级可信。提供路径与调用限额约束，**不是** OS 级沙箱。

## 分层

```text
CLI → SkillRuntime → Discovery / Loader / Executor
                      ResourceGuard / ScriptRunner
Executor → LLMClient（tools）→ 三工具回调
```

## 新鲜度

- 默认 `SKILL_FINGERPRINT_MODE=content`：已扫描文件内容哈希
- 跨 `list`/`load`/`run`：指纹变化则刷新
- 单次 `run`：锁定入口清单与说明；读/执行仍对磁盘现读；不热更新

## 脚本

- `asyncio.create_subprocess_exec`，`cwd`=Skill 根
- 合计输出 `OutputBudget`（加锁流式追加）
- 脚本超时与 Agent 总超时均可杀进程组并释放信号量

## 错误

见 `skill.errors`：NotFound / NameConflict / InvalidFormat / MissingMetadata /
ResourceNotFound / ResourceForbidden / Execution / Script。
