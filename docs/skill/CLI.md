# Skill CLI

```bash
uv run skill list --skills-dir DIR
uv run skill inspect NAME --skills-dir DIR
uv run skill run NAME --task "..." --skills-dir DIR [--context '{"k":"v"}']
```

各子命令均支持 `--skills-dir` / `--env-file`。

- `--skills-dir`：覆盖为单个 Skill 根目录（其下一层子目录为各 Skill）
- 配置见 `.env` 中 `SKILL_*`（`SKILL_ROOTS` 多根用 `:` 分隔）
