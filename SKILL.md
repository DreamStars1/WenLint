---
name: zh-prose-smell
description: 中文散文坏味检查器——jieba 分词+词表规则，检测文档中的 AI 腔/废话填充、模糊词、空洞强调、重复词、超长句。写中文文档（PRD/论文/给医生的材料/任何 markdown）后或检查 AI 生成内容时使用。用法：python scripts/zh_prose_smell.py <文件或目录>。
---

# zh-prose-smell：中文散文坏味检查器

把"代码异味"检测思路搬到中文散文：快速、免费、确定性揪出写作中的高频毛病。
定位 = 浅层确定性检测器（Checkstyle 之于代码坏味），语义级问题留给 LLM/人。

## 何时使用

- 用户写完中文文档/PRD/论文/报告，要求"检查一下写作/有没有 AI 味/用词问题"
- 检查 AI 生成内容是否带 AI 腔（对外交付的文档尤其需要）
- 用户提到 vale / prose lint / 散文坏味 / prose smell

## 执行原则（先查找，后询问）

用户要求检查/修复但没指明具体文件时，按顺序自行定位，**不要直接问"检查哪个文件"**：
1. 工作区/家目录最近的 .md 文档（~ 文档、PRD、论文调研、当前工作目录）
2. 代码库内的 markdown（README、docs、AGENTS.md 等，可用 search_files 找含 AI 腔词的文件）
3. 网络内容（用户给了 URL 或引用网上文本时）
4. 以上都定位不到或歧义大（多个候选不知选哪个）才询问用户

默认用 review 模式（只报告不改文件）；用户明确要改时用 --fix / --fix --apply。

## 依赖

```bash
pip install jieba        # 唯一依赖（中文分词）
```

## 用法

```bash
# 单文件或目录（.md/.txt/.rst）
python <skill_dir>/scripts/zh_prose_smell.py 文档.md
python <skill_dir>/scripts/zh_prose_smell.py <目录>/

# JSON 输出（脚本消费）
python <skill_dir>/scripts/zh_prose_smell.py 文档.md --json

# fix 模式（自动修复：删 AI 腔引导词/重复词，显示 diff 不写盘）
python <skill_dir>/scripts/zh_prose_smell.py 文档.md --fix
# fix + 写盘（先备份 .bak）
python <skill_dir>/scripts/zh_prose_smell.py 文档.md --fix --apply
```

输出格式（vale 风格）：`文件:行:列  级别  类别: 命中的词`

## 两种模式

1. **review（默认）**：只检查报告，不改文件
2. **fix（--fix）**：自动修复后输出 diff；`--apply` 写盘（自动备份 .bak）
   - 自动改：AI 腔引导词（词后接逗号/句读/行尾时）+ 中文相邻重复词
   - 不自动改（fix 后列出待人工/LLM）：定语结构（"综上所述的方案"）、模糊词、强调词、超长句

## 检测类别

| 类别 | 级别 | 抓什么 |
|---|---|---|
| AI味/废话填充 | warning | 总而言之、综上所述、值得注意的是、众所周知、赋能、抓手、闭环、颗粒度…（AI_CLICHE 词表） |
| 模糊词 | warning | 大概、好像、似乎、也许、或许、差不多、一定程度…（FUZZY_WORDS） |
| 空洞强调词 | suggestion | 非常、十分、极其、超级、真的、简直…（EMPTY_EMPHASIS） |
| 重复用词 | warning | jieba 词级相邻重复（"真的真的"） |
| 超长句 | suggestion | 单句 >60 字无断句 |

## Markdown 智能

自动跳过/处理（不误报）：
- 代码块（``` 围栏 + 4 空格缩进）
- 行内代码 `` `code` ``、图片、HTML 标签、注释、删除线
- 链接 URL（保留链接文字参与检查）
- YAML front matter、表格行、标题行

## 自定义词表

编辑脚本顶部 5 个列表（AI_CLICHE / FUZZY_WORDS / EMPTY_EMPHASIS / REDUNDANT / AI_HALLUCINATION_HEDGE）：
- ≤4 字词：jieba 词级精确匹配
- >4 字短语：原文子串匹配（兜底）
把用户不喜欢的词/表达加进去即可，零门槛。

## 设计背景（与 vale 的关系）

vale 是英文 prose linter，按空格分词——中文无空格导致句内词全漏检（实测只命中句首词）。
本工具用 jieba 分词解决中文 token 化，是 vale 思路的中文实现。两者对比如下：

| 维度 | vale | zh-prose-smell |
|---|---|---|
| 中文句内词匹配 | ❌ 漏检 | ✅ 全命中 |
| 规则生态（英文向） | ✅ 丰富 | ❌ 自建词表 |
| markup 支持 | ✅ 深度 | ✅ 常用覆盖 |
| 依赖 | Go 二进制 | Python + jieba |
