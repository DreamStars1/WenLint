---
name: wenlint
description: 检查中文文档写作/AI 味时使用。文尺 WenLint：中文写作静态检查器（发现候选）+ LLM 四分类处理流程。
---

# 文尺 WenLint：中文写作静态检查器

像 ESLint 检查代码一样检查中文 PRD、论文、报告和 Markdown。确定性规则引擎做**发现**，LLM 做**判断与修改**——WenLint 本体不修改正文。

## 何时使用

- 用户写完中文文档/PRD/论文/报告，要求"检查写作/有没有 AI 味/用词问题"
- 检查 AI 生成内容的质量（对外交付的文档尤其需要）
- 用户提到 wenlint / 文尺 / prose lint / 中文写作检查

## 完整工作流（六步，一次跑完）

1. **定位文件**——用户没指明时按顺序自己找：工作区/家目录最近的 .md → 代码库 markdown（search_files 找含套话词的文件）→ 网络（URL 或能搜到的文档）。找不到才问。
2. **运行 wenlint**——`wenlint <path> --json`（工具需已安装：`pip install -e <仓库路径>` 或 `python -m wenlint`）。若 wenlint 命令不存在，用本 skill 所在环境中能访问的安装方式，**不假设固定家目录路径**。
3. **四分类判断**——对每条 finding：先读 `review_hint`（规则已给判断方向），再看 `sentence/before/after` 理解语境：
   - `KEEP` 合理用法（学术审慎/领域术语/有语义的推测/引述示例词）→ 不改，说明理由
   - `REWRITE` 可直接根据上下文改（套话删、`是否能够`→能否、长句拆）
   - `VERIFY` 可核实断言（时间/数量/能力/归因）→ 先检索（见第 4 步）；找到依据 → REWRITE 附依据出处；找不到 → ASK
   - `ASK` 资料不足 → 列疑问请作者确认
4. **VERIFY 检索**——按能力优先级找资料：
   1. 用户当前指定或上传的文件；
   2. 当前项目/工作区内的相关文档（需求文档/PRD/README）；
   3. 用户文件库中的相关资料（本地搜索）；
   4. 用户给出的 URL 或可 web 搜索的公开资料；
   5. 都找不到才 ASK。
   依据必须可追溯（文件:行/URL），禁止编造出处
5. **只改确认要改的局部**——交互约定：
   - 用户只说"检查"→ 只给报告不修改
   - 用户说"帮我修"→ 自动处理所有确定的 REWRITE，**最后给一份合并 diff**
   - VERIFY 找到依据的一起修改并注明来源；ASK 集中询问真正缺信息的项
   - 高风险/大范围改写才在写入前逐条确认；无依据不删不确定词（`可能/大概`）
   - 除非用户明确要"整体润色"，不做全文润色
6. **输出摘要**——KEEP/REWRITE/VERIFY/ASK 分开列，REWRITE 带 before → after，最后列未解决的 ASK

## 运行

```bash
python -m wenlint 文档.md              # 文本输出（在 wenlint 包目录内或 pip install -e .）
python -m wenlint . --profile academic # 论文场景
python -m wenlint 文档.md --json       # 结构化输出（供四分类流程消费）
python -m wenlint . --fail-level warning  # CI：有 >= warning 时 exit 1
```

## 输出格式

`文件:行:列  规则ID  级别  类别  message`（vale 风格）
`--json` 每条含：rule/type/severity/category/message/review_hint/file/line/column/text/sentence/before/after（**无 replacement**——WenLint 不知道该怎么改）。

## 规则速查

- **C001/C003** 套话引导词（`总而言之/由此可见…`；词后接"的/之"定语结构自动豁免）
- **C002** 术语滥用（`赋能/抓手/闭环…`，candidate 需语义判断）
- **H001** 模糊词硬（`大概/好像/差不多`）；**H002** 模糊词软（`可能/或许`，candidate）；**H003** `左右` 歧义（candidate）
- **E001** 空洞强调（`非常/真的…`）；**R001** 冗余动词（`进行`+动词）；**R002** `是否能够`
- **D001** 相邻重复词；**S001** 超长句（文档 80 / SKILL.md 50，跨行段落聚合）；**A900** SKILL.md 主文件过载

candidate 级命中不阻断 CI（--fail-level 只认 warning+），交由语义层裁决。

## Markdown 行为（与实现一致）

- 跳过：标题行、表格行、代码块（围栏/缩进）、行内代码、HTML 标签与注释（含多行）、front matter、图片、链接 URL
- 检查：散文段落、列表项文字、引用块、**链接文字**（列号精确）、**引号与括号内正文**（示例词等元语境由语义层判 KEEP，不由规则层静默放过）
- 自动跳过目录：.git/.venv/node_modules/build/dist/__pycache__ 等
