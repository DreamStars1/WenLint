# Hallmark 对 WenLint 的可借鉴点

研究日期：2026-09-15。只读查阅 Nutlope/hallmark 的 main 分支原始文件；未安装或执行该项目。main 会变动，本文不是固定提交的复现报告。

## 结论

适合吸收的是规则组织和交付验收方法，而非整套反 AI 风格禁令。WenLint 已有全文语义审查、四类问题、禁止编造出处和逐条确认；应加强现有链路，不另造重复审查体系。

## 值得吸收

1. **规则写成可解释的条目。** Hallmark 的反模式采用“命名现象—原因—修复”，审计输出再带严重度和位置。WenLint 可统一规则卡为“原文位置、触发证据、实际阅读问题、最小修改、适用文体、例外”，便于用户判断是否采纳；不要只写“有 AI 味”。[anti-patterns.md](https://github.com/Nutlope/hallmark/blob/main/skills/hallmark/references/anti-patterns.md#L334-L349)
2. **改写后有具体验收。** Hallmark 在交付前执行分项门禁，并要求状态反映真实结果。迁移到写作时，建议把人名、日期、数值、引文、否定、范围限定、责任主体列为不变量；比对改写前后，标出无法确认项。对格式、数字可确定性检查，对语义保真做独立复核，不以模型自评分代替验证。[slop-test.md](https://github.com/Nutlope/hallmark/blob/main/skills/hallmark/references/slop-test.md#L0-L20)
3. **通用规则与文体规则分开。** Hallmark 区分通用与 genre 范围，并按执行阶段加载参考文档。WenLint 可据 profile 加载学术、商务、产品说明等规则；基础格式常驻，细分文体和改写验收按需加载。[SKILL.md](https://github.com/Nutlope/hallmark/blob/main/skills/hallmark/SKILL.md#L310-L319)
4. **无证据时改变表达结构。** Hallmark 不允许为了填满统计区而杜撰数字，可保留待确认位置或移除不成立的统计结构。WenLint 已禁止编造出处，增量价值是：提示作者补证、降低断言强度或删掉没有证据的论证模块，而非自动“润色”出可信度。[anti-patterns.md](https://github.com/Nutlope/hallmark/blob/main/skills/hallmark/references/anti-patterns.md#L168-L172)
5. **前端使用语义 token 和状态验收。** Hallmark 要求颜色、字体引用命名变量，检查交互状态与减弱动态效果。主线程本地核查显示 WenLint 已有 tokens 和 focus-visible，但部分 token 名称与颜色不符、仍有硬编码，可先统一命名和引用，再补实际缺少的状态。[SKILL.md](https://github.com/Nutlope/hallmark/blob/main/skills/hallmark/SKILL.md#L374-L391)

## 不宜照搬

- **风格不等于作者来源。** Hallmark 将重复构图等视为 AI 特征，这是设计偏好，不能迁移成“用了某词即 AI 写作”的判定依据。WenLint 应报告可观察的表达缺陷，允许专业术语和必要固定句式。[anti-patterns.md](https://github.com/Nutlope/hallmark/blob/main/skills/hallmark/references/anti-patterns.md#L0-L4)
- **不能为了变化强迫换结构。** 它强调连续产物结构差异；制度、周报、论文常需要稳定模板。写作的结构建议必须服从文体和用户要求。[slop-test.md](https://github.com/Nutlope/hallmark/blob/main/skills/hallmark/references/slop-test.md#L30-L33)
- **规则不能覆盖用户明确意图。** 反模式文档甚至要求某些装饰禁令优先于用户“保持既有结构”的要求。WenLint 应保留用户授权边界；特别是飞书写回继续遵守现有逐项确认流程。[anti-patterns.md](https://github.com/Nutlope/hallmark/blob/main/skills/hallmark/references/anti-patterns.md#L117-L124)
- **门禁数量与自评分不是质量证明。** README 写 57，核心文件写 58；门禁细节也混有审美断言。应维护规则版本、真实执行结果与未覆盖项，不能套用“全部通过”的宣传式状态。[README](https://github.com/Nutlope/hallmark#hallmark)、[slop-test.md](https://github.com/Nutlope/hallmark/blob/main/skills/hallmark/references/slop-test.md)

## 建议优先顺序

1. 在现有改写链路增加事实与语义不变量验收，并明确失败/待确认原因。
2. 统一规则卡格式，再按文体 profile 精简加载，保留现有四分类。
3. 全文结构审查复用已有能力；主线程发现超过 6000 字符会分块，先解决跨块论证、术语一致性和重复结论的覆盖问题。
4. 前端收敛语义 tokens，核对实际控件状态、窄屏和 reduced-motion 支持。

以上迁移建议是结合 WenLint 场景的推论；Hallmark 没有提供中文写作检测算法或证明这些规则能可靠判断文本作者来源的评测。
