# Anti-AI-Slop Writing 对 WenLint 的可借鉴点

研究日期：2026-09-15。只读查阅远端 main 的 README、SKILL.md 和 banned-words.md，并对照本地 SKILL.md、README.md、AGENTS.md、规则及 Agent 提示。main 会变动；本次未安装或执行远端代码。

## 结论

值得借鉴的是语义检查角度和场景校准。它是一套英文写作指令，不能直接成为中文静态规则或 AI 来源判定器。[README](https://github.com/jalaalrd/anti-ai-slop-writing)

## 值得吸收的增量

以下是对文尺的建议，并非已经实现：

| 借鉴方向 | 文尺落点 | 判断边界 |
| --- | --- | --- |
| 评价落到具体对象与行为 | 全文审查追问“提升效率”具体改善哪一步、如何衡量 | 有资料就 VERIFY；缺资料 ASK，不能凭空补数字 |
| 检查短句之间的关系 | 核对连续陈述是否缺因果、条件或转折 | 简明步骤、并列事实应 KEEP，不按句长机械合并 |
| 检查空泛对比句 | “不仅 X，更 Y”可作为 candidate，判断对比是否提供新信息 | 真实纠错、范围区分应保留 |
| 作者与渠道校准 | 将目标读者、投放渠道、已有文风作为可选审查上下文 | 仅提示不合适的格式；不默认整篇口语化 |

前三项来自原始规则的结构和具体性要求；第四项来自 Voice Calibration 与 Formatting Rules。[SKILL.md](https://github.com/jalaalrd/anti-ai-slop-writing/blob/main/skills/anti-ai-slop-writing/SKILL.md)；对比句候选借鉴词表中的句式类型。[banned-words.md](https://github.com/jalaalrd/anti-ai-slop-writing/blob/main/skills/anti-ai-slop-writing/references/banned-words.md)

## 已有基础，不重复建设

- 文尺已有 KEEP / REWRITE / VERIFY / ASK、局部修改和查证流程。[本地 SKILL](../../SKILL.md)
- E001 已要求检查具体程度、数据或例证；Agent 已禁止捏造事实、数据、来源和用户意图。增量在补充语义案例，而非再建一套“具体化”规则。[rules.py](../../wenlint/rules.py)、[agent.py](../../wenlint/agent.py)
- profile 已区分学术等场景，academic 关闭 H002。作者声音和投放渠道可在此基础上增加上下文。[README](../../README.md)

## 不宜照搬

远端把三项列举、句长、被动句、标点等设为硬约束，也要求限制反方表述。这些偏好不适合作为论文、PRD 的通用门禁。正文允许真实三项，自检又要求拆三项；禁止连续短句又鼓励碎句，说明移植前必须明确例外。[SKILL.md](https://github.com/jalaalrd/anti-ai-slop-writing/blob/main/skills/anti-ai-slop-writing/SKILL.md)

英文禁词与模型常用首词不宜直接翻译成中文禁令；专业术语、正常连接词仍需结合语境。已读文件虽提到研究名称，却没有可复验的实验材料支持其检测效果；本次不采信“消除可检测 AI 模式”的效果承诺。[banned-words.md](https://github.com/jalaalrd/anti-ai-slop-writing/blob/main/skills/anti-ai-slop-writing/references/banned-words.md)、[README](https://github.com/jalaalrd/anti-ai-slop-writing)

## 推荐下一步

先整理“应改／应保留／需查证”中文对照样例，覆盖空泛对比、关系缺失、无据具体化；让现有语义审查试用并记录误报，再决定是否新增 candidate。此次只新增研究笔记，未修改产品代码。
