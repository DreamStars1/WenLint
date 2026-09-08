# 参与 WenLint

感谢你帮助改进中文文档质量工具。请优先提交小而可验证的变更。

## 开发环境

```bash
python -m pip install -e ".[test]"
python -m pytest -q --basetemp=.pytest-basetemp-local
```

桌面界面还需要 Node.js 与 pnpm：

```bash
cd desktop-ui
pnpm install --frozen-lockfile
pnpm run build
```

## 提交流程

1. 新规则需提供正例、误报例和 Markdown 边界测试。
2. Agent 与桌面桥接变更不得记录 API Key 或文档正文。
3. 用户原文件不得被默认覆盖；写操作必须由用户明确触发。
4. 提交前运行完整 pytest 与 Vue 生产构建。
5. Pull Request 说明动机、行为变化、验证命令和兼容性影响。

规则命中不是最终判断。语义候选应保持 `candidate`，由 KEEP / REWRITE / VERIFY / ASK 流程裁决。
