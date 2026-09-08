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

1. **定位输入**——用户没指明时按顺序自己找：工作区/家目录最近的 .md → 代码库 markdown → 网络文档。若输入是飞书 `/docx/` 或 `/wiki/` URL，改走 `references/feishu.md`（`wenlint-feishu`）；本地路径（含字面名为 `feishu` 的文件）仍用 `wenlint`。用户只给裸 token 时，仅在其明确声明是飞书文档后才按飞书处理。找不到才问。
2. **运行检查**——本地：`wenlint <path> --json`。飞书：见 `references/feishu.md`。若命令不存在，用本 skill 所在环境中能访问的安装方式，**不假设固定家目录路径**，也**不静默安装** Python/`lark-cli`。飞书检查前必须区分以下两种情况：
   - `lark-cli` 确实未安装：停止检查并提示用户先按官方方式运行 `npx @larksuite/cli@latest install`，再完成 `lark-cli config init` 与用户身份授权；不要代用户安装、初始化应用或扩大 OAuth scope。
   - `lark-cli` 已安装，但当前 Agent 进程的 `PATH` 不可见（Windows NVM/Codex 运行时常见）：不要要求用户重新初始化。提示用户用 Windows 的 `where.exe lark-cli` 或 macOS/Linux 的 `command -v lark-cli` 获取实际路径，并将 `WENLINT_LARK_CLI` 设置为可执行文件路径后重试。Windows 应优先使用 `lark-cli.cmd`，不要使用同目录下无扩展名的 Unix 启动脚本。此环境变量只保存可执行文件路径，禁止写入 App Secret 或 access token。
   - 飞书 JSON 含顶层 `coverage`：准确汇报静态覆盖度；`semantic_review` 在 Python inspect 中始终为 `not_run`。
   - **分流**：用户只要求「跑 WenLint / 检查措辞 / AI 味」→ 静态检查 + finding 四分类，并准确汇报 coverage。用户要求「详细 / 全文 / 细粒度 / 逻辑 / 需求完整性 / 还有没有工具漏报」→ 必须读取全文并执行下方产品语义 lenses，**不得**仅依赖 inspect findings。
3. **四分类判断**——对每条静态 finding：先读 `review_hint`（规则已给判断方向），再看 `sentence/before/after` 理解语境：
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
   - 本地用户说"帮我修"→ 自动处理所有确定的 REWRITE，**最后给一份合并 diff**
   - 飞书用户要求写回 → 必须先总览再逐章批准（见 `references/feishu.md`）；未明确批准不写
   - VERIFY 找到依据的一起修改并注明来源；ASK 集中询问真正缺信息的项
   - 高风险/大范围改写才在写入前逐条确认；无依据不删不确定词（`可能/大概`）
   - 除非用户明确要"整体润色"，不做全文润色
   - DOC001/DOC002 与表格单元格 finding 只报告，**禁止**进入自动写回 / patch manifest
6. **输出摘要**——KEEP/REWRITE/VERIFY/ASK 分开列，REWRITE 带 before → after，最后列未解决的 ASK。若语义审查未运行，最终**不得**使用「全文通过」「没有问题」等表述。

```text
静态规则未命中 ≠ 全文已经语义审查 ≠ 文档没有问题
```

## 产品全文语义审查（lenses）

触发：用户要求详细 / 全文 / 细粒度 / 逻辑 / 需求完整性，或询问工具是否漏报；`product` profile 默认按下列 lenses 逐章与跨章节审查（读取全文，不依赖 findings=[]）：

1. 结构完整性与术语一致性
2. 当前稿自洽与上下文独立：核对讨论过程、纠偏说明、版本演变残留，以及「先…再… / 不再 / 仍然」的顺序、旧状态和比较基线
3. 条件是否能由现有数据证明
4. 空值、默认值和未知态
5. 状态生命周期、去重、关闭和重开
6. 时间点、时区、宽限和迟到数据
7. 事务、幂等、重试、补偿和并发
8. 权限、隐私、审计和通知暴露
9. 验收条件、反例、灰度、监控和回滚

语义 finding 使用 `severity + category + action + evidence + locations`。`KEEP/REWRITE/VERIFY/ASK` 只表示下一步动作，不代替严重度。
## 运行

```bash
python -m wenlint 文档.md              # 本地文本输出
python -m wenlint . --profile academic # 论文场景
python -m wenlint 文档.md --json       # 结构化输出（供四分类流程消费）
python -m wenlint . --fail-level warning  # CI：有 >= warning 时 exit 1
wenlint-feishu <docx-or-wiki-url> --json  # 飞书只读检查（细节见 references/feishu.md）
```

飞书 Docx/Wiki 的检查与写回见 `references/feishu.md`。
## 输出格式

`文件:行:列  规则ID  级别  类别  message`（vale 风格）
`--json` 每条含：rule/type/severity/category/message/review_hint/file/line/column/text/sentence/before/after（**无 replacement**——WenLint 不知道该怎么改）。

## 规则速查

- **C001/C003** 套话引导词（`总而言之/由此可见…`；词后接"的/之"定语结构自动豁免）
- **C002** 术语滥用（`赋能/抓手/闭环…`，candidate 需语义判断）
- **H001** 模糊词硬（`大概/好像/差不多`）；**H002** 模糊词软（`可能/或许`，candidate）；**H003** `左右` 歧义（candidate）
- **M001** 讨论/纠偏/版本演变过程痕迹；**M002** `先…再…/不再/仍然` 等上下文依赖表述（均为 candidate，必须结合当前稿核对，不能见词就删）
- **E001** 空洞强调（`非常/真的…`）；**R001** 冗余动词（`进行`+动词）；**R002** `是否能够`
- **D001** 相邻重复词；**S001** 超长句（文档 80 / SKILL.md 50，跨行段落聚合）；**A900** SKILL.md 主文件过载
- **DOC001** 空标题（warning，结构，不可自动写回）
- **DOC002** 同级显式数字编号断层（candidate，默认仅 `product` profile，不可自动写回）

candidate 级命中不阻断 CI（--fail-level 只认 warning+），交由语义层裁决。

## Markdown 行为（与实现一致）

- 跳过：代码块（围栏/缩进）、行内代码、HTML 标签与注释（含多行）、front matter、图片、链接 URL、表格 delimiter 行
- 标题：不做词法套话扫描；跑 DOC001/DOC002 结构检查（`headings=structure_only`）
- 表格：每个单元格独立跑词法规则与 S001/D001（列号指向词首；不跨单元格拼接）
- 检查：散文段落、列表项文字、引用块、**链接文字**（列号精确）、**引号与括号内正文**（示例词等元语境由语义层判 KEEP，不由规则层静默放过）
- 自动跳过目录：.git/.venv/node_modules/build/dist/__pycache__ 等
