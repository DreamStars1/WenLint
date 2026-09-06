# zh-prose-smell：中文散文坏味检查器

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

把"代码异味"检测思路搬到中文散文：jieba 分词 + 词表规则，快速免费揪出高频写作毛病。

vale 按空格分词，中文整句成块、句内词漏检（实测只命中句首）；本工具为中文重做，jieba 版全量命中。

## 安装

```bash
pip install jieba        # 唯一依赖

# 作为 CLI 使用
git clone <本仓库> zh-prose-smell
# 或作为 Hermes skill：把整个仓库放入 ~/.hermes/skills/productivity/zh-prose-smell/
```

## 用法

```bash
# 模式一：review（只检查，默认）
python scripts/zh_prose_smell.py 文档.md
python scripts/zh_prose_smell.py 论文调研目录/

# 模式二：fix（自动修复 + 显示 diff，不写盘）
python scripts/zh_prose_smell.py 文档.md --fix

# 模式二 + 写盘（先自动备份 .bak）
python scripts/zh_prose_smell.py 文档.md --fix --apply

# JSON 输出（供脚本消费）
python scripts/zh_prose_smell.py 文档.md --json
```

### fix 模式的安全规则

**自动改**（语义无损）：
- 删除 AI 腔引导词：`总而言之、综上所述、值得注意的是、众所周知…`（仅当词后接逗号/句读/行尾）
- 中文相邻重复词去重：`真的真的` → `真的`

**绝不自动改**（留给人工/LLM，fix 后报告列出）：
- 定语结构：如 `综上所述的方案`（删了破坏句法）——词后接"的/之/地"时跳过
- 模糊词（`大概/可能/好像`）——删除改变语义确定性
- 空洞强调词（`非常/真的/超级`）——语气取舍因人而异
- 超长句——需要理解语义才能拆

## 输出示例

```
test/zh.md:1:1   warning     AI味/废话填充: 总而言之
test/zh.md:1:10  suggestion  空洞强调词: 非常
test/zh.md:1:19  warning     模糊词: 大概
test/zh.md:7:5   suggestion  空洞强调词: 非常
```

格式仿 vale：`文件:行:列  级别  类别: 命中的词`

## 检测类别

| 类别 | 级别 | 抓什么 |
|---|---|---|
| **AI味/废话填充** | warning | `总而言之、综上所述、值得注意的是、众所周知、毋庸置疑、不难发现、赋能、抓手、闭环、颗粒度…` |
| **模糊词** | warning | `大概、好像、似乎、也许、或许、差不多、一定程度…` |
| **空洞强调词** | suggestion | `非常、十分、极其、超级、真的、简直…` |
| **重复用词** | warning | jieba 词级相邻重复（`这个这个`、`真的真的`） |
| **超长句** | suggestion | 单句 >60 字无断句（跳过代码块/表格行） |

## Markdown 智能

- ✅ 自动跳过代码块（``` 围栏 + 缩进代码），只查正文
- ✅ 自动跳过表格行、标题行（不误报超长句）
- ✅ 输出行:列定位

## 扩展词表

编辑脚本顶部的列表即可：

```python
AI_CLICHE = ["总而言之", "赋能", "抓手", ...]      # 你讨厌的 AI 腔
FUZZY_WORDS = ["大概", "可能", ...]                # 模糊词
EMPTY_EMPHASIS = ["非常", ...]                     # 空洞强调
```

词的匹配 = jieba 分词词级命中（≤4字词）+ 短语子串兜底（>4字），自己加词零门槛。

## 设计说明

- **为什么不用 vale 原版**：vale 的 existence 规则按空格 token 匹配，中文无空格。
  - 实测 `总而言之`（句首）能命中，但句内 `非常/大概/真的` 全部漏检。
  - 中文场景 vale 需先 jieba 分词插空格预处理（行号偏移+维护成本），不如独立脚本干净。
- **为什么需要词表**：prose smell 的本质是"高频模式检测"（同 code smell 的规则检测层），
  - 词表可解释、可审计、可扩展——正是 vale 哲学与代码坏味研究交叉的地方。
- **层级定位**：本工具 = 确定性浅层检测器（等价 Checkstyle 之于代码坏味）；
  - 语义级坏味（结构性啰嗦、逻辑跳跃）留给 LLM 精判——可做两段式。

## 仓库结构

```
zh-prose-smell/
├── SKILL.md                # Hermes skill 定义（触发条件/执行原则/用法）
├── scripts/
│   └── zh_prose_smell.py   # 主脚本（词表 + 检测 + 修复逻辑都在此）
├── test/                   # 测试样例（markup 陷阱、fix 用例）
├── LICENSE                 # MIT
└── README.md
```

## 许可证

[MIT](LICENSE) © 2026 DreamStars1。自由使用、修改、分发，保留版权声明即可。
