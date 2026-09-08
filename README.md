# 文尺 WenLint

中文写作静态检查器——像 ESLint 一样检查你的 PRD、论文、报告和 Markdown。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

不是"AI 味检测器"。AI 套话只是其中一类规则。
它以**确定性规则引擎**发现问题：快速、可解释、可复现；桌面版再由用户配置的 LLM Agent 裁决并生成修改稿。

```
README.md:18:7   C001  warning     套话/废话填充  「总而言之」
paper.md:42:16   H001  warning     模糊词         「大概」
prd.md:76:1      S001  suggestion  超长句         94 chars
```

## 安装

### Python 引擎（pipx / venv）

需要 **Python 3.11+**（推荐 3.13；CI 覆盖 3.11 / 3.13 / 3.14）。运行时无第三方 Python 依赖；飞书能力另需本机 `lark-cli`。

```bash
pipx install git+https://github.com/DreamStars1/WenLint.git  # PyPI 发布前从仓库安装
python -m pip install -e ".[test]"   # 开发：可编辑安装 + pytest
# 或直接运行： python -m wenlint <path>
```

### Windows / macOS 桌面版（Vue）

面向不使用命令行的用户，桌面版提供完整工作台：打开或拖入 UTF-8 文本、关联一个本地工作区、选择检查场景、本地静态检查、填写 OpenAI-compatible `Base URL` / `API Key` / 模型名称，再由内置 Agent 并发执行“静态候选裁决”和“全文独立发现”并生成修改稿。通过 Python 安装桌面命令时请使用 `python -m pip install ".[desktop]"`；发布的应用包已内置运行环境。

- Windows 完整解压后打开 `WenLint/WenLint.exe`；Mac 解压后打开 `WenLint.app`，无需单独安装 Python 或 Node。
- API Key 只保存在当前进程内存中，不写配置文件或日志。
- 点击 Agent 审查前会明确提示将正文发送到哪个模型服务；启用工作区查证后，Agent 可以按需搜索和读取相关文本片段，工具参数与结果在过程面板中可展开查看。
- “尚未复核”“复核失败”“已完成但无改动”使用不同状态，完成时间、耗时和模型调用数会在结果区显示。
- 工作区只索引支持的文本文件，忽略版本库、依赖和构建目录；用户可逐个打开文件并审查。
- 改写默认逐条待确认；只有“采纳建议”的改动进入修改稿，可保留原文、撤销决定并核对全文。
- 修改用 GitHub 风格的行级 diff 展示：原/新双行号、删除行 `−`、新增行 `+`，并突出实际变化的字词；未变化的上下文保持中性。
- 超过6000字符时启用长文会话：核心段最多4000字符、前后各最多300字符上下文；每批最多两段，显示已覆盖范围并由用户决定是否继续。续查保留已采纳/保留的决定，原文或配置改变后须重新审查。
- Agent 的计划、工具调用、工具结果和决策依据实时可见，支持取消；展示可审核的摘要，不记录模型内部思维链。
- 参考资料按页读取（默认40行、最多4000字符），长单行有字符续页游标；搜索明确标注预算截断，不把未搜索区域误称为已查。
- “保存”经再次确认后覆盖原文件，“另存为”创建新文件，“应用到编辑区”只更新当前编辑内容。覆盖前会校验文件未被外部修改。

下载 [v0.6.1 桌面应用](https://github.com/DreamStars1/WenLint/releases/tag/v0.6.1)：提供 Windows x64、Apple 芯片 Mac 和 Intel Mac 三种 ZIP，附校验和与构建清单。开发者可在 Windows 上构建：

```powershell
python -m pip install -e ".[test,desktop-build]"
./scripts/build-windows.ps1 -Python python
# 输出：dist/WenLint/WenLint.exe（保留整个目录）
```

标签 `v*` 或手动触发 `build-desktop` 工作流时，CI 在 Windows x64、macOS arm64 和 macOS x64 原生环境分别运行测试、构建目录应用并做无界面 smoke test，上传 ZIP、SHA-256 和依赖清单；标签构建在全部平台成功后统一发布 GitHub Release。Windows 目录分发减少单文件反复解包的启动开销。Mac 本地可运行 `bash scripts/build-macos.sh`。当前构建未使用发布者签名或 Apple 公证，首次启动可能需要系统批准；详见 [分发说明](docs/competition/DISTRIBUTION.md)。

### 演示材料

无需密钥，打开桌面应用后点击“体验示例”。也可运行 `python -m wenlint.browser_demo`，在浏览器打开 `http://127.0.0.1:8765`；浏览器入口仅运行明确标注的离线模拟，不调用模型。

性能与知识查证记录见 [验收记录](docs/competition/VALIDATION.md)。真实 DeepSeek V4 Flash 短句审查一次实测2.32秒；短句工作区查证一次8.48秒。独立桌面体验者完成267字审查、逐项确认及原生导出，用时23.5秒并发现漏查参考资料。修复后的[最终桌面复测](docs/competition/FINAL_DESKTOP_REVIEW.md)用时28.0秒，实际读取两份参考资料并验证diff、逐条确认和LF导出；其中候选关联错位另在0.6.1修复，只有离线回归。单次结果不代表长文或所有网络环境，模型引用行号仍需核对。

仓库内置了可重复验证的 [桌面版演示包](demo/README.md)，包含故意保留问题的待审查文档、多文件工作区、事实基线、静态结果快照、参考修改稿和人工验收清单。在仓库根目录运行 `python demo/verify_demo.py` 可验证材料未漂移。

### 参赛材料

本项目面向 [2026 上海开源软件应用创新大赛](https://www.oschina.net/os2026/) 准备，建议选报开源 AI 工具赛道。仓库内提供 [项目介绍、架构、治理、验证与交付索引](docs/competition/README.md)；报名、邮件提交和视频由参赛人完成。

### Codex Skill（npx skills）

```bash
npx skills add DreamStars1/WenLint --skill wenlint --agent codex --global
```

`npx skills` 只分发 Skill 文档与工作流，**不会**安装 Python 运行时或 `lark-cli`。飞书检查前请确认 `wenlint-feishu` 与 `lark-cli` 可用。

若 `lark-cli` 报 executable missing，常见原因是当前 shell 的 Node/PATH 与安装 CLI 的 Node 版本不一致（例如 NVM 未切换）。请自行切换到安装了 `lark-cli` 的 Node 版本，或设置 `WENLINT_LARK_CLI` 指向可执行文件；WenLint **不会**自动安装、扫描用户目录或执行 `nvm use`。

适配器会按 `lark-cli` 帮助能力选择 JSON 方言：旧版显式传递 `--format json`，新版依赖默认 JSON 输出。已离线验证 legacy 与 modern（含默认 JSON、`data.document.content`、`id` 属性）两种方言；兼容性以能力探测为准，不以版本号字符串为唯一条件。

## 用法

```bash
wenlint 文档.md                     # review：发现候选
wenlint docs/                       # 目录
wenlint . --profile academic        # 论文场景（H002 学术词关闭、长句放宽 80）
wenlint . --fail-level warning      # 严格门禁：有 >= warning 时 exit 1
wenlint 文档.md --json              # 结构化输出（供 Skill/LLM 消费）
wenlint-feishu <docx-or-wiki-url> --json   # 飞书 Docx/Wiki 只读检查
wenlint-feishu apply <url> --patch-file m.json --json  # 仅应用已批准章节 patch
wenlint-desktop                       # 启动 Vue 桌面工作台（开发安装）
```

**WenLint 核心扫描器不修改正文**——核心定案：只做“发现”。
飞书写回由 Skill 逐章批准后，通过 `wenlint-feishu apply` 执行局部 `block_replace`；inspect 路径永不写入。
发现结果 = 定位 + 规则 ID + 命中文本 + 上下文 + review_hint；
判断/查证/改写交给 Skill 的 LLM，或桌面版中用户显式调用的内置 Agent（见下“职责划分”）。
## 规则

| ID | 规则 | 级别 | 说明 |
|---|---|---|---|
| C001 | cliche-intro 套话引导词 | warning | `总而言之/值得注意的是/众所周知…`（词后接逗号/句读才删） |
| C002 | buzzword 术语滥用 | candidate | `赋能/抓手/闭环/颗粒度…`（语义判断：领域术语 KEEP / 空话 REWRITE） |
| C003 | 套话 | warning | `由此可见`（block：`由此可见一斑`） |
| H001 | 模糊词（硬） | warning | `大概/好像/似乎/差不多` |
| H002 | 模糊词（软） | candidate | `可能/或许/也许…`（academic profile 关闭；语义判断：合理 hedge KEEP / 无据断言 VERIFY） |
| H003 | `左右` 歧义 | candidate | `左右边/两侧/手/翼` 空间义自动豁免 |
| M001 | revision-history 过程痕迹 | candidate | 讨论、纠偏、修正和版本演变表述；核对成稿是否只需保留当前结论 |
| M002 | context-dependent-transition | candidate | `先…再…/不再/仍然…`；核对顺序、旧状态、时间点和比较基线是否完整 |
| E001 | 空洞强调 | suggestion | `非常/十分/真的/超级…` |
| R001 | 冗余动词 | suggestion | `进行` + 动词（语境正则，如"进行分析"） |
| R002 | 冗余表达 | suggestion | `是否能够` → `能否` |
| D001 | 相邻重复词 | warning | `语义风险，留给人工` |
| S001 | 超长句 | suggestion | 文档 80 字；SKILL.md 收紧 50 字 |
| DOC001 | empty-heading 空标题 | warning | ATX / 飞书投影空标题；不可自动写回 |
| DOC002 | numbered-heading-gap | candidate | 同父同级显式数字编号向前跳号；默认仅 `product`；不可自动写回 |

## 规则结构（不是"词=坏味"，是规则引擎）

```python
{
  "id": "R001",                    # 规则 ID（可 ignore/配置）
  "category": "冗余结构",
  "severity": "suggestion",
  "patterns": [r"进行(?=(分析|讨论|研究|说明))"],   # 语境正则
  "block": None,                   # 例外（如"由此可见一斑"）
  "message": "…",
  "review_hint": "给 LLM 的判断方向（查证/保留条件/改写建议）",
}
```

`可能` 在论文里是重要学术审慎（epistemic hedge），在营销软文里则算含糊——所以分 H001/H002 级。
`进行` 只有后接动词才算冗余——所以 R001 用语境正则。这才是 ESLint 式规则，不是敏感词扫描。
M001/M002 同样只负责发现候选：决策日志中的纠偏记录可能必须保留，`先校验、再写入` 也可能是完整且必要的顺序。Skill 需要阅读全文，核对当前基线和前后依赖后再决定 KEEP/REWRITE/VERIFY/ASK。

## Markdown 智能与位置精确

- 等长 mask（内容替换为等长空格）→ **行号列号与原文一一对应**，front matter 存在也不错位
- 自动跳过：代码块（围栏/缩进）、行内代码、HTML 标签与注释（含多行）、图片、front matter、表格 delimiter 行
- 标题：结构检查 DOC001/DOC002（不做套话词法扫描）
- 表格：单元格独立扫描词法与句长（列号精确）
- 链接：URL 不查，**链接文字照查（列号精确，不偏移）**
- **引号与括号内正文照常检查**——元语境（示例词/引述）由语义层判 KEEP，不由规则层静默放过
- 词规则在正文行（段落/列表/引用块）与表格单元格执行；目录扫描自动跳过 .git/.venv/node_modules/build 等

```text
静态规则未命中 ≠ 全文已经语义审查 ≠ 文档没有问题
```

飞书 `inspect --json` 额外返回协议字段 `coverage`（不由 finding 数量推导；Python 侧 `semantic_review` 恒为 `not_run`）：

```json
{
  "coverage": {
    "static": {
      "paragraphs": "scanned",
      "list_items": "scanned",
      "blockquotes": "scanned",
      "headings": "structure_only",
      "table_cells": "scanned",
      "code": "excluded",
      "embedded_resources": "excluded"
    },
    "semantic_review": "not_run"
  }
}
```

本地 `wenlint --json` 仍输出 finding 数组，本阶段不迁移到新的顶层 envelope。

## 职责划分

**WenLint 扫描器是工具，Skill 或桌面 Agent 负责语义判断。**

| WenLint（发现） | Skill / LLM（判断与修复） |
| --- | --- |
| Markdown-aware 定位 | 判断是否误报 |
| 正则/词表/统计匹配 | 理解上下文 |
| `可能`、`大概` 等候选发现 | 判断是真不确定还是懒得查 |
| 讨论/纠偏史与上下文依赖措辞候选 | 核对当前稿基线、顺序和跨章节依赖 |
| 冗余表达候选发现 | 根据语义重写 |
| 输出行号、span、上下文、review_hint | 搜索文件库 |
| 稳定、可测试 | 根据找到的依据修改 |
| **不修改正文** | **负责 fix** |

**Skill 对每条命中做四分类判断**（不是简单"改写"）：

```
KEEP     无需修改（合理用法/学术审慎/领域术语）
REWRITE  可直接根据上下文修改
VERIFY   需先查已有资料再修改（搜到依据 → REWRITE + 附依据）
ASK      资料也不足，需要作者确认（绝不在无依据时删"可能"）
```

**修复纪律**：LLM 只允许修改 WenLint 指出的局部，除非用户明确要求"整体润色"——
避免从"检查`可能`是否合理"滑向"把整篇文风改一遍"。

## 输出 Schema（--json，供 Skill 消费）

```json
{
  "rule": "H002",
  "type": "candidate",
  "severity": "candidate",
  "category": "模糊词",
  "message": "模糊词「可能」——论文/技术文档中如需保留学术审慎可忽略",
  "review_hint": "判断该陈述是否属于可从已有资料核实的事实；若是，优先检索资料…",
  "file": "prd.md",
  "line": 18,
  "column": 7,
  "text": "可能",
  "sentence": "系统目前可能支持 Excel 批量导入。",
  "before": "当前版本已经完成患者管理模块。",
  "after": "具体能力以需求文档为准。"
}
```

**不输出 `replacement`**——WenLint 不知道该怎么改，判断属于 Skill。


## CI 与门禁

- **默认只输出报告，不做强制门禁**——规则命中不等于真问题：
  C001/H001 等 warning 级规则也会被 LLM 判 KEEP（如引述示例词）。
- `--fail-level warning` 只用于**严格场景**（已知干净的文档防回归）。
- 等真实语料验证规则精度（KEEP 率统计）后，再决定哪些规则有资格阻断 CI。

## 数据驱动的规则收敛（roadmap）

拿 20-30 篇真实文档跑一轮，记录每条 finding 最终判 KEEP/REWRITE/VERIFY/ASK，
按规则统计 KEEP 比例。某条规则大部分命中都是 KEEP → 降级 candidate 或移除。
这个反馈数据比继续扩充词表更有价值。

### 本地反馈记录（无网络）

`wenlint-feedback` 把四分类结果追加到本地 JSONL，**不上传、无遥测**，仅供本机统计：

```bash
wenlint-feedback record \
  --decision KEEP --rule H002 --file docs/prd.md --line 18 --column 7 \
  --text 可能 --reason "属于合理的学术审慎" --profile academic \
  --output .wenlint/feedback.jsonl

wenlint-feedback stats --input .wenlint/feedback.jsonl --json
```

每条记录含 `schema_version`、`decision`、`rule`、`file`、`line`、`column`、
`text`、`reason`、`profile`、`recorded_at`（UTC，`Z` 后缀）。
`decision` 仅允许 `KEEP` / `REWRITE` / `VERIFY` / `ASK`。

## 配置

- **profile**：`academic/product/formal/general`（词表分级 + 参数调整；`product` 启用 DOC002）
- **自定义规则**：编辑 `wenlint/rules.py`（后续迁 `wenlint.toml`）
- **忽略文件**：项目根 `.wenlintignore`（glob；`tests/` 尾斜杠 = 目录前缀）

## 开发

```bash
pip install -e ".[test]"
python -m pytest tests/     # 完整回归测试（本地扫描 + 飞书适配器）

cd desktop-ui
pnpm install --frozen-lockfile
pnpm run build              # Vue 生产资源
```

提交规范、安全问题报告方式和公开路线图分别见 [CONTRIBUTING.md](CONTRIBUTING.md)、[SECURITY.md](SECURITY.md) 与 [ROADMAP.md](ROADMAP.md)。

## 仓库结构

```
wenlint/
├── wenlint/
│   ├── rules.py         # 规则数据声明（ID/pattern/block/review_hint）
│   ├── scanner.py       # 扫描引擎（mask 后规则分发 + 语言守卫）
│   ├── markdown.py      # Markdown 保护层（行角色分类 + 等长 mask）
│   ├── cli.py           # 本地文件路由 + review 步骤编排
│   ├── agent.py         # OpenAI-compatible Agent + 严格 JSON 契约
│   ├── desktop.py       # pywebview 本地桥接（文件/扫描/Agent/保存）
│   ├── feedback.py      # 本地四分类反馈 JSONL（无网络）
│   ├── feishu/          # 飞书 Docx/Wiki 检查与安全写回（wenlint/feishu/）
│   └── __init__.py      # 版本
├── tests/               # pytest 回归（本地 + 飞书）
├── desktop-ui/          # Vue 3 + Vite 桌面界面
├── scripts/             # Windows / macOS 原生应用构建入口
├── pyproject.toml       # packaging（含 wenlint-desktop）
├── LICENSE              # MIT
└── README.md
```

## 许可证

[MIT](LICENSE) © 2026 Zheng Haipei（郑海培）。自由使用、修改、分发，保留版权声明即可。
