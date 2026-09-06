---
name: wenlint
description: 检查中文文档写作/AI 味时使用。文尺 WenLint：中文写作静态检查器（发现候选，不修改正文）。
---

# 文尺 WenLint：中文写作静态检查器

像 ESLint 检查代码一样检查中文 PRD、论文、报告和 Markdown。确定性规则引擎（词法模式/套话/模糊词/冗余/长句），**只负责发现，不修改正文**。

## 何时使用

- 用户写完中文文档/PRD/论文/报告，要求"检查写作/有没有 AI 味/用词问题"
- 检查 AI 生成内容的质量（对外交付的文档尤其需要）
- 用户提到 wenlint / 文尺 / prose lint / 中文写作检查

## 执行原则（先查找，后询问）

用户没指明具体文件时，按顺序自行定位，不要问"检查哪个文件"：
1. 工作区/家目录最近的 .md 文档（~ 文档、PRD、论文调研、当前工作目录）
2. 代码库内 markdown（README/docs/AGENTS.md；用 search_files 找含套话词的文件）
3. 网络内容：用户给 URL，或能 web 搜索定位的文档/知识（提到某文章/标准先自己搜）
4. 定位不到或歧义大（多个候选）才询问用户

## 运行

```bash
python -m wenlint 文档.md              # 需在 wenlint 包目录内，或 pip install -e .
python -m wenlint . --profile academic # 论文场景
python -m wenlint 文档.md --json       # 结构化输出（带 sentence/review_hint）
```

## 核心定案：WenLint 只发现，Skill 负责判断与修复

WenLint 输出 = 定位 + 规则 ID + 命中文本 + 上下文 + review_hint；**没有 --fix**。
真正的修改流程在 wenlint-semantic skill（本 skill 的下游）：
对每条 finding 做四分类——KEEP（合理用法保留）/ REWRITE（直接改）/
VERIFY（先查资料再改，附依据）/ ASK（资料不足问作者）。

判断、查证、改写交给 LLM；**只改 WenLint 指出的局部**，不默认全文润色。

## 输出格式

`文件:行:列  规则ID  级别  类别  message`

```
README.md:18:7  C001  warning  套话/废话填充  套话「总而言之」，删掉更直接
```

`--json` 每条含：rule/type/severity/category/message/review_hint/file/line/column/text/sentence/before/after（无 replacement）。

## 规则速查

- **C001** 套话引导词（总而言之/综上所述…）；**C003** 由此可见（block 一斑）
- **C002** 术语滥用（赋能/抓手/闭环…，semantic 候选）
- **H001** 模糊词硬（大概/好像/差不多）；**H002** 模糊词软（可能/或许，candidate）；**H003** `左右` 歧义（candidate）
- **E001** 空洞强调（非常/真的…）；**R001** 冗余动词（进行+动词）；**R002** 是否能够
- **D001** 相邻重复词；**S001** 超长句（文档 80 / SKILL.md 50）；**A900** 主文件过载

## 深入检查

语义层判断（哪些是真问题、查证、改写）走 **wenlint-semantic** skill：
`wenlint --json` 输出 → 逐条四分类 → 检索 → 报告 KEEP/REWRITE/VERIFY/ASK。
