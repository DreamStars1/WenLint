# 文尺 WenLint

中文写作静态检查器——像 ESLint 一样检查你的 PRD、论文、报告和 Markdown。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

不是"AI 味检测器"。AI 套话只是其中一类规则。
它是**确定性规则引擎**：快速、可解释、可复现，留好接 LLM 语义审查的接口。

```
README.md:18:7   C001  warning     套话/废话填充  「总而言之」
paper.md:42:16   H002  suggestion  模糊词         「大概」
prd.md:76:1      S001  suggestion  超长句         94 chars
```

## 安装

```bash
pip install -e .             # 本地安装，获得 wenlint 命令（仅标准库依赖）
# 或直接运行： python -m wenlint <path>
```

## 用法

```bash
wenlint 文档.md                     # review：发现候选
wenlint docs/                       # 目录
wenlint . --profile academic        # 论文场景（H002 学术词关闭、长句放宽 80）
wenlint . --fail-level warning      # CI：有 >= warning 时 exit 1
wenlint 文档.md --json              # 结构化输出（供 Skill/LLM 消费）
```

**WenLint 不修改正文**——v0.1 核心定案：只做"发现"。
发现结果 = 定位 + 规则 ID + 命中文本 + 上下文 + review_hint；
判断/查证/改写全部交给 Skill 的 LLM（见下"职责划分"）。

## 规则

| ID | 规则 | 级别 | 说明 |
|---|---|---|---|
| C001 | cliche-intro 套话引导词 | warning | `总而言之/值得注意的是/众所周知…`（词后接逗号/句读才删） |
| C002 | buzzword 术语滥用 | candidate | `赋能/抓手/闭环/颗粒度…`（语义判断：领域术语 KEEP / 空话 REWRITE） |
| C003 | 套话 | warning | `由此可见`（block：`由此可见一斑`） |
| H001 | 模糊词（硬） | warning | `大概/好像/似乎/差不多` |
| H002 | 模糊词（软） | candidate | `可能/或许/也许…`（academic profile 关闭；语义判断：合理 hedge KEEP / 无据断言 VERIFY） |
| H003 | `左右` 歧义 | candidate | `左右边/两侧/手/翼` 空间义自动豁免 |
| E001 | 空洞强调 | suggestion | `非常/十分/真的/超级…` |
| R001 | 冗余动词 | suggestion | ❌ | `进行` + 动词（语境正则，如"进行分析"） |
| R002 | 冗余表达 | suggestion | ✅ | `是否能够` → `能否` |
| D001 | 相邻重复词 | warning | `语义风险，留给人工` |
| S001 | 超长句 | suggestion | 文档 80 字；SKILL.md 收紧 50 字 |

## 规则结构（不是"词=坏味"，是规则引擎）

```python
{
  "id": "R001",                    # 规则 ID（可 ignore/配置）
  "category": "冗余结构",
  "severity": "suggestion",
  "patterns": [r"进行(?=(分析|讨论|研究|说明))"],   # 语境正则
  "block": None,                   # 例外（如"由此可见一斑"）
  "fixable": False,                # 只有高置信规则才自动修
  "message": "…",
}
```

`可能` 在论文里是重要学术审慎（epistemic hedge），在营销软文里则算含糊——所以分 H001/H002 级。
`进行` 只有后接动词才算冗余——所以 R001 用语境正则。这才是 ESLint 式规则，不是敏感词扫描。

## Markdown 智能与位置精确

- 等长 mask（内容替换为等长空格）→ **行号列号与原文一一对应**，front matter 存在也不错位
- 自动跳过：标题行、表格行、代码块（围栏/缩进）、行内代码、HTML 标签与注释（含多行）、图片、front matter
- 链接：URL 不查，**链接文字照查（列号精确，不偏移）**
- **引号与括号内正文照常检查**——元语境（示例词/引述）由语义层判 KEEP，不由规则层静默放过
- 词规则只在正文行执行（段落/列表/引用块）；目录扫描自动跳过 .git/.venv/node_modules/build 等

## 职责划分（v0.1 定案）

**WenLint 是工具，Skill 是 Agent。**

| WenLint（发现） | Skill / LLM（判断与修复） |
| --- | --- |
| Markdown-aware 定位 | 判断是否误报 |
| 正则/词表/统计匹配 | 理解上下文 |
| `可能`、`大概` 等候选发现 | 判断是真不确定还是懒得查 |
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


## 配置与扩展

- **profile**：`academic/product/formal/general`（词表分级 + 参数调整）
- **自定义规则**：编辑 `wenlint/rules.py`（v0.2 迁 `wenlint.toml`）
- **CI**：`--fail-level warning`，命中即 exit 1

## 开发

```bash
pip install pytest
python -m pytest tests/     # 26 个回归测试（mask/行号/scope 行为/CLI）
```

## 仓库结构

```
wenlint/
├── wenlint/
│   ├── rules.py         # 规则数据声明（ID/pattern/block/review_hint）
│   ├── scanner.py       # 扫描引擎（mask 后规则分发 + 语言守卫）
│   ├── markdown.py      # Markdown 保护层（行角色分类 + 等长 mask）
│   ├── cli.py           # 路由 + review 步骤编排
│   └── __init__.py      # 版本
├── tests/               # pytest 回归（17 tests）
├── pyproject.toml       # packaging（wenlint 命令）
├── LICENSE              # MIT
└── README.md
```

## 许可证

[MIT](LICENSE) © 2026 Zheng Haipei（郑海培）。自由使用、修改、分发，保留版权声明即可。
