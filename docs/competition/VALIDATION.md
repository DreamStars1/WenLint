# 可复现验证与验收记录

本文件区分离线回归、模型服务测试与真实图形界面体验。测试运行速度不能直接当作用户体验或远程模型的延迟保证。

## 运行方法

```bash
python -m pip install -e ".[test]"
python -m pytest -q --basetemp=.pytest-basetemp-validation
python demo/verify_demo.py
cd desktop-ui
pnpm install --frozen-lockfile
pnpm test
pnpm run build
```

完整流程使用 [demo 文档与事实基线](../../demo/README.md)：打开待审查文档，先静态检查，按需选择 demo 工作区，再运行 Agent。确认能够看到进度、工具动作与结果说明；逐条接受或拒绝修改，核对全文后另存为。保存前应确认未接受建议不会进入输出，原文件被外部更改时不会被静默覆盖。

## 验收口径

| 维度 | 要验证的行为 | 记录方式 |
|---|---|---|
| 首次使用 | 无项目背景的体验者能理解起点、完成检查与另存为 | 记录实际点击、困惑点、错误及修复，不将 agent 体验当作真实人群研究 |
| 即时反馈 | 点击检查后及时出现本地结果或明确的任务状态 | 测量点击到首个可见反馈，独立于模型总耗时 |
| 模型响应 | 能看到阶段变化、已完成的工作与失败说明 | 记录首事件、首模型输出、完成耗时及调用次数 |
| 控制权 | 逐项确认、取消/失败后重试、保存保护 | 自动回归 + 实际桌面操作 |
| 知识利用 | 能找到 demo 事实基线，资料不足时保留待核实状态 | 核对工具记录、引用片段与实际源文件 |
| 平台分发 | 包可导入运行时且包含资源，实际窗口可打开 | 每平台 packaged `--self-test` + 人工窗口验收 |

产品目标：本地检查与操作状态尽量在 1 秒内反馈，短 demo 的在线审查争取在 30 秒内完成；外部服务超过目标时仍须给出进度及取消入口。这些是工程验收目标，不是已达到的测量结论，也不是对所有文档/服务的 SLA。

## 实测结果

2026-09-09，本地 Windows 11 / Python 3.13.15。单次在线观测仅用于冒烟，不代表平均延迟、长文表现或事实准确率。浏览器/桌面展示另有 250ms 轮询及渲染开销。

| 测试 | 当前证据 |
|---|---|
| Python 完整回归 | `python -m pytest -q --basetemp=.pytest-goal-final-full`：294 passed，360.30s；最终相关模块复核 51 passed，0.77s |
| 前端测试与生产构建 | `pnpm test` 8/8；`pnpm build` 成功；桌面界面契约 3/3 |
| demo 快照一致性 | `python demo/verify_demo.py`：17 条静态候选、3 个工作区文件、参考修改稿通过 |
| 本地检查 / 首事件延迟 | 30次短文静态检查 P95 0.18ms；后台任务启动1.21ms、首次轮询事件1.22ms，见 [离线记录](../../demo/evidence/response-time-offline.json) |
| 真实模型 smoke test | DeepSeek `deepseek-v4-flash`：短句首模型输出1.137s、完成2.317s、2次请求，见 [在线记录](../../demo/evidence/response-time-live.json)；工作区事实查证完成8.478s、3次请求、5次只读工具调用，指出20/30秒和Windows支持平台冲突并引用文件行号，见 [知识查证记录](../../demo/evidence/response-time-knowledge.json) |
| 新用户视角流程 | 独立子agent从空白页面走通演示、采纳/保留/撤销、全文核对与另存为反馈；[原始体验及复测限制](FIRST_USER_REVIEW.md)。模拟体验不是人类用户研究 |
| Windows 打包与窗口 | Python 3.13.15 / PyInstaller 6.22.2 目录构建和内置许可收集成功；packaged `--self-test`退出0。原生0.6.0窗口打开并验证演示、改写默认待确认、采纳后的全文及原生另存为对话框。窗口最大化后1280×752布局可用；实际保存文件本体尚未通过UI验证 |
| macOS arm64 / x64 | 待远程原生构建成功；窗口体验待对应 Mac 验证 |

推送后需将成功 Actions 运行链接和产物 SHA-256 加入发行记录。测试通过不能替代赛事审核、模型事实准确率评测或 macOS 人工体验。

分发工具验证：PowerShell 脚本经 PowerShell AST 解析无错误，macOS 脚本经 Git Bash `bash -n` 通过；依赖声明收集在 Windows 虚拟环境成功处理 22 个 Python 分发及已安装的前端包。原生 Mac 构建不能由上述语法检查替代。

## 性能回归命令与发现

`python scripts/verify-response-time.py` 验证静态P95<100ms、任务启动<200ms、首次事件<250ms、离线完成<1s。加 `--live` 使用环境变量 `WENLINT_BASE_URL`、`WENLINT_MODEL`、`WENLINT_API_KEY`，在线完成门槛30s；再加 `--knowledge` 必须实际调用工具且引用demo事实基线才算通过。脚本不会打印或保存密钥。

真实模型测试曾暴露同句静态改写重叠使整份审查失败、模型跳过已启用的查证、工具结果后未输出JSON。已分别修为冲突建议转ASK、查证先获取工具观察、DeepSeek JSON模式，并加回归；上述在线记录为修复后的真实结果，未以模拟响应替代。

旧0.5.0单文件包与新目录包各执行三次`--self-test`进程启动测量：中位数2602.91ms→942.84ms（约64%下降），见 [样本](../../demo/evidence/packaged-startup.json)。包含进程启动和导入自检，不包含GUI渲染，不是冷启动控制实验。

Cursor独立只读审查复现了取消后重试被阻挡和离线来源误标。取消后允许一个替代任务、仍限制同时存活后台任务；演示统一标注本地模拟、真实工具参数和结果仅作为纯文本展开。首次使用者P2来源和P3固定按钮修改后已由主agent在原生Windows窗口复核，独立体验者的浏览器复测因浏览器连接不可用而未完成。
