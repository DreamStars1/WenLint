# WenLint 覆盖度与产品文档审查增强规格

日期：2026-09-08
状态：Implemented and accepted（2026-09-08）
范围：WenLint Python 核心、Feishu inspect 协议、Codex Skill 与测试

## 1. 背景

一次真实飞书产品方案检查返回 `findings=[]`，随后被错误表述为“全文通过”。人工阅读全文后仍发现了空标题、章节编号断层、表格内数据语义矛盾，以及状态、时间、幂等、生命周期和验收条件缺失。

这暴露了三个不同问题：

1. 静态检查的覆盖范围没有进入公开结果，调用者无法区分“未命中”与“未检查”。
2. 标题和表格被当作 Markdown 结构整体跳过，恰好遗漏产品文档中信息密度最高的区域。
3. Skill 的语义流程只审查已有 finding；当 finding 为零时，不会主动执行全文产品语义审查。

WenLint 仍坚持“确定性工具负责发现，Skill / LLM 负责判断与修复”。本规格不在 Python 包内引入模型调用。

## 2. 目标

### 2.1 必须实现

1. Feishu inspect JSON 明确返回静态覆盖度和语义审查状态，不能暗示零 finding 等于全文无问题。
2. 标题进入独立的结构检查，至少发现空标题和显式数字编号断层。
3. Markdown 与 Feishu 表格单元格进入现有词法规则扫描；Feishu 表格 finding 必须只报告、不可自动写回。
4. `product` profile 对标题编号结构检查提供明确策略，不再只是 `general` 的别名。
5. Skill 在用户要求“详细 / 全文 / 细粒度 / 逻辑 / 需求完整性”审查时，即使静态 finding 为零，也必须读取全文并执行产品语义 lenses。
6. README 和 Skill 明确区分：静态规则未命中、语义审查未运行、全文审查完成。
7. 发现并核对成稿中的讨论过程、纠偏说明、版本演变痕迹，以及依赖旧上下文的顺序或状态措辞。

### 2.2 非目标

- 不在 `wenlint` 或 `wenlint-feishu` Python 进程内调用 LLM。
- 不把幂等、生命周期、隐私等领域问题实现为脆弱的关键词正则。
- 不自动写回结构或语义 finding。
- 不改变现有逐章批准、revision、fingerprint 和 `block_replace` 安全模型。
- 不要求普通 `wenlint file.md --json` 从 JSON 数组迁移到新的顶层 envelope；本阶段保持本地 CLI 兼容。

## 3. 术语

- **静态 finding**：由确定性规则生成，可稳定复现。
- **结构 finding**：以标题、编号或文档结构为对象的静态 finding。
- **语义 finding**：由 Skill / LLM 基于全文和多个证据点生成。
- **覆盖度**：本次工具运行实际扫描过的内容类型，而不是质量结论。
- **零命中**：本次已启用静态规则没有产生 finding；不等于全文无问题。

## 4. 模块设计

### 4.1 扫描入口

保留 `scan_text(text, profile, filename)` 作为兼容接口。其实现内部可以拆分，但调用者不需要学习多个扫描函数。

该接口负责组合：

1. 现有正文词法规则；
2. 表格单元格词法规则；
3. 标题结构规则；
4. 现有文件级规则。

所有 finding 继续使用现有公共字段。结构 finding 没有可安全替换的文本时，`text` 可以为空，但必须有准确的 `line`、`column`、`sentence` 和 `review_hint`。

### 4.2 新规则

#### DOC001 empty-heading

- 类别：`文档结构`
- 默认级别：`warning`
- 触发：Markdown ATX 标题去掉 `#` 和空白后没有可见标题文本；Feishu 投影中的空标题同理。
- 不触发：代码围栏内的 `#`、水平线、仅出现在正文中的井号。
- 建议：删除空标题或补齐标题。
- 自动写回：否。

#### DOC002 numbered-heading-gap

- 类别：`文档结构`
- 默认级别：`candidate`
- 默认启用：`product` profile。
- 其它 profile：关闭。
- 触发范围：同一直接父标题下、相同标题级别、标题以显式阿拉伯数字层级开头时，序号向前跳过一项。例如 `3.1` 后直接出现 `3.3`。
- 不触发：序号倒退、重复号、罗马数字、非数字标题、跨父章节比较，以及无法安全判断的混合编号。
- finding 指向后一个标题，消息同时给出前一个和当前编号。
- 规则只提示核对；允许作者有意预留章节，因此是 candidate。
- 自动写回：否。

编号解析仅识别类似 `3`、`3.1`、`3.1.2`，可接受末尾 `.`、中文顿号或空白。比较时要求前缀一致，只比较最后一段整数。

### 4.3 表格单元格扫描

#### Markdown

- 识别 GFM pipe table 数据行和表头。
- 跳过 delimiter 行，例如 `|---|:---:|`。
- 每个单元格独立运行词法规则和 D001。
- S001 对每个单元格独立计长，不跨单元格拼接。
- 保持原始行列坐标；转义管道或行内代码不得造成命中列偏移。

#### Feishu XML

- `table` 不再从 analysis projection 中完全丢弃。
- 以稳定的行、单元格分隔符投影可见文字，并为真实文字保留 SourceMap。
- 表格投影中的所有真实文字标记为 `writable=false`，避免自动 patch 破坏表格结构。
- 图片、附件、嵌入 sheet/bitable 和其它已有排除资源继续不进入文字扫描。
- 表格中命中的 finding 必须绑定到可用的 block id；映射状态允许 `exact`，但 `writable` 必须是 `false`，reason 使用稳定值，例如 `table_cell`。

### 4.4 Feishu 覆盖度协议

`InspectionReport.to_dict()` 新增顶层 `coverage`，已有字段保持不变：

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

约束：

- 值使用固定字符串，不使用易误解的布尔值。
- `semantic_review` 在 Python inspect 中始终为 `not_run`；Python 核心不伪装成 LLM 审查。
- coverage 是协议字段，不从当前 finding 数量推导。
- 文档为空时仍返回 coverage。

### 4.5 Skill 全文产品审查

静态检查后增加显式分流：

1. 用户只要求“跑 WenLint / 检查措辞 / AI 味”时，执行静态检查和 finding 四分类，并准确汇报 coverage。
2. 用户要求“详细、全文、细粒度、逻辑、需求完整性、还有没有工具漏报”时，读取全文；不得仅依赖 inspect findings。
3. 对 `product` profile，按以下 lenses 逐章和跨章节审查：
   - 结构完整性与术语一致性；
   - 当前稿自洽与上下文独立：讨论过程、纠偏说明、版本演变残留，以及“先…再… / 不再 / 仍然”的顺序、旧状态和比较基线；
   - 条件是否能由现有数据证明；
   - 空值、默认值和未知态；
   - 状态生命周期、去重、关闭和重开；
   - 时间点、时区、宽限和迟到数据；
   - 事务、幂等、重试、补偿和并发；
   - 权限、隐私、审计和通知暴露；
   - 验收条件、反例、灰度、监控和回滚。
4. 语义 finding 使用 `severity + category + action + evidence + locations` 表达。`KEEP/REWRITE/VERIFY/ASK` 只表示下一步动作，不代替严重度。
5. 若语义审查未运行，最终不得使用“全文通过”“没有问题”等表述。

本阶段 Skill 可以通过现有文档读取能力获取全文，不要求 Python inspect 内嵌全文或原始 XML。

## 5. 兼容性

- 本地 `wenlint --json` 继续输出 finding 数组。
- Feishu inspect 只新增 `coverage`；现有 `source`、`sections`、`findings` 不删除、不改名。
- 新规则遵循现有 `--fail-level` 行为。DOC002 是 candidate，不阻断 CI；DOC001 warning 可按现有阈值阻断。
- 旧调用方忽略未知 JSON 字段即可继续工作。
- 写回流程必须拒绝 DOC001、DOC002 和表格 finding 进入 patch manifest。

## 6. 测试与验收

### 6.1 单元测试

必须覆盖：

1. 空 ATX 标题产生 DOC001。
2. `3.1` 后出现 `3.3`，在 product profile 产生 DOC002。
3. `3.1` 后出现 `3.2` 不报。
4. 不同父标题下的编号不互相比较。
5. general profile 不报 DOC002。
6. Markdown 表格中的 `总而言之` 能产生 C001，列号指向词首。
7. delimiter 行不产生 finding。
8. 表格单元格中的长句按单元格独立判断。
9. Feishu XML 表格中的 H002/C001 能被扫描和定位，但 `writable=false`。
10. 空 Feishu h3 产生 DOC001 且不可写。
11. InspectionReport 始终输出约定的 coverage。
12. `findings=[]` 时 coverage 仍说明 `semantic_review=not_run`。
13. M001 能发现讨论、纠偏和版本演变过程词，输出 candidate 与审查提示。
14. M002 能分别定位“先”“再”“不再”和“仍然”，并豁免“优先、领先、先生、再现、再生”等明显词汇义。

### 6.2 回归测试

- 现有测试全部通过。
- 现有段落、列表、引用块、代码围栏、HTML、链接、SourceMap、章节 fingerprint、逐章写回行为不回归。
- Feishu inspect 不调用任何更新命令。
- 表格扫描不能让 apply 接受表格 patch。

### 6.3 脱敏验收样本

新增一个最小 fixture，包含：

```markdown
### 3.1 数据来源

| 状态 | 含义 |
| --- | --- |
| status=0 | 未处理 |

###

### 3.3 其它来源
```

在 product profile 下必须得到：

- 一个 DOC001；
- 一个 DOC002；
- coverage 指明 table cells 已扫描、semantic review 未运行。

不要尝试用静态规则判断 `status=0` 的业务语义矛盾；该问题由 Skill 的全文 lens 发现。

## 7. 文档要求

README 和 SKILL 必须出现以下等价表述：

```text
静态规则未命中 ≠ 全文已经语义审查 ≠ 文档没有问题
```

README 应给出 Feishu coverage JSON 示例；SKILL 应给出详细审查触发条件和 product lenses。

## 8. 完成定义

满足以下全部条件才算完成：

- 本规格 6.1 的测试全部存在并通过；
- 全量测试通过；
- 公开 JSON 兼容约束满足；
- README、SKILL 和实现一致；
- 无 LLM 运行时依赖；
- 无飞书写回安全回归；
- 未重置、覆盖或清理工作区中已有改动；
- 未提交、推送或创建 PR。

## 9. 验收记录

- Cursor 按本规格完成实现；独立验收未采用执行代理的自报结果。
- 专项回归：`tests/test_coverage_and_structure.py`，31 项通过。
- 全量回归：223 项通过。
- `git diff --check` 通过。
- 额外边界验收覆盖代码围栏、front matter、多行 HTML 注释、部分单元格注释、行内代码、转义竖线、无前导竖线表格及非法分隔行。
- 未执行飞书写回、commit、push 或 PR 操作。
