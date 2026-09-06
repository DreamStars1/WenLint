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
pip install jieba            # 运行时依赖（可选，部分规则用）
pip install -e .             # 本地安装，获得 wenlint 命令
# 或直接运行： python -m wenlint <path>
```

## 用法

```bash
wenlint 文档.md                     # review
wenlint docs/                       # 目录
wenlint . --profile academic        # 论文场景（H002 学术词关闭、长句放宽 80）
wenlint README.md --fix             # 修复预览（不写盘）
wenlint README.md --fix --apply     # 写回（先备份 .bak）
wenlint . --fail-level warning      # CI：有 >= warning 时 exit 1
wenlint 文档.md --json              # 机器可读
```

## 规则

| ID | 规则 | 级别 | fixable | 说明 |
|---|---|---|---|---|
| C001 | cliche-intro 套话引导词 | warning | ✅ | `总而言之/值得注意的是/众所周知…`（词后接逗号/句读才删） |
| C002 | buzzword 术语滥用 | warning | ❌ | `赋能/抓手/闭环/颗粒度…` |
| C003 | 套话 | warning | ✅ | `由此可见`（block：`由此可见一斑`） |
| H001 | 模糊词（硬） | warning | ❌ | `大概/好像/似乎/差不多` |
| H002 | 模糊词（软） | suggestion | ❌ | `可能/或许/也许…`（academic profile 关闭） |
| H003 | `左右` 歧义 | suggestion | ❌ | `左右边/两侧/手/翼` 空间义自动豁免 |
| E001 | 空洞强调 | suggestion | ❌ | `非常/十分/真的/超级…` |
| R001 | 冗余动词 | suggestion | ❌ | `进行` + 动词（语境正则，如"进行分析"） |
| R002 | 冗余表达 | suggestion | ✅ | `是否能够` → `能否` |
| D001 | 相邻重复词 | warning | ❌ | `语义风险，留给人工` |
| S001 | 超长句 | suggestion | ❌ | `>60 字（academic 80）` |

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

## 安全 fix（Markdown-safe）

fix 与 review 共用**等长 mask**：代码块、行内代码、URL、引号等受保护内容全部屏蔽。

```
请不要修改 `总而言之` 行内代码        → 不动
我把"总而言之"作为例子              → 不动（引号保护）
总而言之，这个方案很好              → 自动删（高置信）
综上所述的方案需要讨论               → 不动（定语结构保护）
```

## Markdown 智能与位置精确

- 等长 mask（内容替换为等长空格）→ **行号列号与原文一一对应**，front matter 存在也不错位
- 自动跳过：代码块、行内代码、图片、HTML、注释、表格行、标题行
- 链接：URL 不查，**链接文字照查**

## 两段式设计（v0.2 roadmap）

```
第一层 deterministic lint（本工具）
    词法/句法表面模式/重复/长度/Markdown 结构 —— 本地、快、可解释

第二层 semantic review（可选，LLM）
    逻辑跳跃/段落重复/论证空洞/主语漂移 —— 单独输出

lint warning        = 确定性规则（可复现、可 CI）
semantic advisory   = LLM 判断（绝不伪装成 lint）
```

## 配置与扩展

- **profile**：`academic/product/formal/general`（词表分级 + 参数调整）
- **自定义规则**：编辑 `wenlint/rules.py`（v0.2 迁 `wenlint.toml`）
- **CI**：`--fail-level warning`，命中即 exit 1

## 开发

```bash
pip install pytest
python -m pytest tests/     # 22 个回归测试（mask/行号/fix 安全/CLI）
```

## 仓库结构

```
wenlint/
├── wenlint/
│   ├── rules.py         # 规则引擎定义（ID/语境/例外/profiles）
│   ├── engine.py        # 等长 mask + scan + 安全 fix
│   ├── cli.py           # 命令行
│   └── __init__.py      # 版本
├── tests/               # pytest 回归（22 tests）
├── pyproject.toml       # packaging（wenlint 命令）
├── LICENSE              # MIT
└── README.md
```

## 许可证

[MIT](LICENSE) © 2026 Zheng Haopei（郑海培）。自由使用、修改、分发，保留版权声明即可。
