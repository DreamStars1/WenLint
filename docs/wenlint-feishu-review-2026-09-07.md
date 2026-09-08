# Wenlint 飞书文档检查与写回报告

## 1. 检查对象

- 文档：[基层随访外部系统接口对接需求](https://xml3rop6i5.feishu.cn/wiki/XzkEwaRhtii5X9kVII2cyyoLnQc)
- 检查日期：2026-09-07
- Wenlint 版本：0.2.0
- Node.js：22.14.0（通过 NVM 切换）
- 飞书 CLI：`lark-cli 1.0.93`
- 写回方式：飞书 CLI `docs +update --command block_replace`
- 文档 revision：6 → 12

## 2. 检查结论

首次扫描共发现 7 条候选：

| 分类 | 数量 | 说明 |
| --- | ---: | --- |
| REWRITE | 6 | S001 超长句，已拆分并写回 |
| KEEP | 1 | C002“闭环”，属于有明确业务对象的领域术语 |
| VERIFY | 0 | 无需检索其他资料核实 |
| ASK | 0 | 无需向作者补充确认 |

完成写回后的全文复扫结果：

- 原有 6 条 S001 超长句均已消失。
- 仅剩 1 条 C002“外部闭环”候选，经语义判断为 KEEP。
- 最终 revision 为 12，共识别 54 个章节节点。
- 所有飞书 CLI 写入均返回 `success`，`warnings` 为空。

## 3. 长句原文与修改意见对比

### 3.1 EXT-04 请求体：归档记录返回规则

Wenlint 结果：S001，87 字，超过 80 字阈值。

原文：

> EXT-04 只返回有效的已归档随访记录，作废记录不用于展示和预填，因此不增加 `includeVoided` 请求字段，也不返回容易与我方执行状态混淆的外部 `recordStatus`。

修改后：

> EXT-04 只返回有效的已归档随访记录。作废记录不用于展示和预填。因此，本接口不增加 `includeVoided` 请求字段，也不返回容易与我方执行状态混淆的外部 `recordStatus`。

修改说明：将“返回范围”“作废记录用途”和“接口字段约束”拆成三层，保留原有因果关系。

### 3.2 EXT-04 慢阻肺字段：编码来源与公共字段

Wenlint 结果：S001，126 字，超过 80 字阈值。

原文：

> 示例值只表达业务含义，管控等级、吸入装置使用和体征选项的最终编码必须由东软通过 EXT-05 提供：
> 慢阻肺页面的症状、血压、身高、当前/目标体重、当前/目标 BMI、心率、吸烟、饮酒、运动、心理调整、遵医行为、服药依从性、药物不良反应和用药明细复用公共字段。

修改后：

> 示例值仅表达业务含义。管控等级、吸入装置使用和体征选项的最终编码必须由东软通过 EXT-05 提供：
> 慢阻肺页面复用以下公共字段：症状、血压、身高、当前/目标体重、当前/目标 BMI 和心率。吸烟、饮酒、运动、心理调整、遵医行为、服药依从性、药物不良反应和用药明细也复用公共字段。

修改说明：先单独说明示例值的作用，再交代编码来源；公共字段按“体征”和“生活方式及用药”拆分。此次命中实际跨越两个飞书段落，写回时分别替换了两个 block。

### 3.3 东软页面字段核对：接口控制字段

Wenlint 结果：S001，111 字，超过 80 字阈值。

原文：

> `submissionId`、`sourceRecordId`、`externalPatientId`、待访来源、挂号/预约/接待队列标识、机构编码、病种编码、质控规则版本和提交时间属于接口关联与幂等控制字段，不是东软页面新增录入项。

修改后：

> `submissionId`、`sourceRecordId`、`externalPatientId`、待访来源和挂号/预约/接待队列标识，用于接口关联和幂等控制。机构编码、病种编码、质控规则版本和提交时间也属于控制字段。这些字段均不是东软页面新增录入项。

修改说明：按“来源标识”“其他控制字段”“与页面字段的关系”拆成三句。

### 3.4 EXT-05 响应体：字典覆盖范围

Wenlint 结果：S001，139 字，超过 80 字阈值。

原文：

> 字典至少覆盖病种、随访方式、各病种症状、心理调整、遵医行为、服药依从性、药物不良反应、随访分类、摄盐情况、足背动脉搏动、低血糖反应、慢阻肺其他体征、慢阻肺管控等级、吸入药物装置使用情况、mMRC 分级、CAT 得分区间、气流受限 GOLD 分级和 GOLD 综合评估分组。

修改后：

> 字典至少覆盖病种、随访方式、各病种症状、心理调整、遵医行为、服药依从性、药物不良反应和随访分类。此外还需覆盖摄盐情况、足背动脉搏动和低血糖反应。慢阻肺相关字典包括其他体征、管控等级、吸入药物装置使用情况、mMRC 分级、CAT 得分区间、气流受限 GOLD 分级和 GOLD 综合评估分组。

修改说明：将清单分为通用项目、其他病种项目和慢阻肺项目，提高扫描与人工核对效率。

### 3.5 EXT-07 请求体：病种字段引用

Wenlint 结果：S001，82 字，超过 80 字阈值。

原文：

> 请求中的 `record.formData` 统一使用 EXT-04 定义的公共字段和对应病种字段：高血压按第 7.3.2 节，2 型糖尿病按第 7.3.3 节，慢阻肺按第 7.3.4 节。

修改后：

> 请求中的 `record.formData` 统一使用 EXT-04 定义的公共字段和相应病种字段。高血压、2 型糖尿病和慢阻肺分别按第 7.3.2、7.3.3 和 7.3.4 节执行。

修改说明：将字段来源和病种章节映射拆开，减少冒号后长枚举。

### 3.6 EXT-07 请求体：慢阻肺必填规则

Wenlint 结果：S001，85 字，超过 80 字阈值。

原文：

> 慢阻肺当前仅按已确认的页面必填规则校验，不得要求截图未显示且未经确认的 `resultType`、`referral`、`nextFollowupDate` 或 `entryStaffNo`。

修改后：

> 慢阻肺当前仅按已确认的页面必填规则校验。对于截图未显示且未经确认的 `resultType`、`referral`、`nextFollowupDate` 或 `entryStaffNo`，不得设为必填。

修改说明：将正向校验范围和禁止设置的字段拆开，使约束更直接。

## 4. 保留项

规则：C002，候选词“闭环”。

原文：

> 若东软写入必须关联门诊来源，则人工建单只能完成我方内部随访，不能标记为外部闭环。

处理结论：KEEP。

“外部闭环”在此处表示外部系统写入及状态完成链路，有明确业务对象，并非“打造闭环”一类无实际含义的套话，因此不修改。

## 5. 本次写回过程

1. 通过 NVM 切换到安装了飞书 CLI 的 Node.js 22.14.0。
2. 使用 `docs +fetch --scope keyword --detail with-ids` 精确定位目标段落。
3. 对同一 block 中的多条修改合并处理。
4. 使用明确的 revision 和 block ID 执行 `block_replace`。
5. 每次写入后重新 fetch，验证内容并获取最新 revision 与 block ID。
6. 写回完成后重新执行 Wenlint 全文扫描。

本次共更新 6 个飞书 block。未使用 `str_replace`、`overwrite`、模糊匹配或强制写入。

## 6. Wenlint 遇到的问题

### 6.1 新版飞书 CLI 被错误判定为不兼容

Wenlint 硬编码检测并传递 `--format json`，但 `lark-cli 1.0.93` 已默认输出 JSON，并移除了该参数，因此兼容性探测直接失败。

相关代码：[`wenlint/feishu/lark.py`](../wenlint/feishu/lark.py#L26)、[`wenlint/feishu/lark.py`](../wenlint/feishu/lark.py#L186)。

### 6.2 fetch 响应结构不兼容

Wenlint 读取 `data.content` 并要求 `document.url`；当前 CLI 返回 `data.document.content`，且 fetch 响应没有 URL。

相关代码：[`wenlint/feishu/inspection.py`](../wenlint/feishu/inspection.py#L61)、[`wenlint/feishu/inspection.py`](../wenlint/feishu/inspection.py#L70)。

### 6.3 block ID 属性名称不兼容

当前 CLI 返回的 XML 使用 `id="..."`。Wenlint 只识别 `block-id` 和 `block_id`，导致章节中的 block ID 为空，普通词规则也无法建立可写映射。

相关代码：[`wenlint/feishu/projection.py`](../wenlint/feishu/projection.py#L304)、[`wenlint/feishu/sections.py`](../wenlint/feishu/sections.py#L61)。

### 6.4 S001 不提供可绑定的命中文本

S001 finding 的 `match` 固定为空字符串。因此即使识别出长句，飞书定位阶段也只能得到 `empty_match` 和 `writable=false`，无法生成安全 patch。

相关代码：[`wenlint/scanner.py`](../wenlint/scanner.py#L112)、[`wenlint/scanner.py`](../wenlint/scanner.py#L129)。

### 6.5 相邻飞书 block 被聚合成同一句

飞书投影使用换行分隔相邻段落，而 S001 会聚合连续的 paragraph 行。这使“示例值”与下一段“慢阻肺页面字段”被识别为一条跨 block 长句。

相关代码：[`wenlint/scanner.py`](../wenlint/scanner.py#L202)、[`wenlint/scanner.py`](../wenlint/scanner.py#L227)。

### 6.6 update 响应中的 revision 可能滞后

部分 `docs +update` 响应返回的 revision 仍是写入前版本，重新 fetch 后才能得到新 revision。因此不能直接把 update 响应中的 revision 当作下一次写入基准。

## 7. 优化建议

| 优先级 | 优化项 | 建议方案 |
| --- | --- | --- |
| P0 | 兼容新版 CLI | 移除对 `--format json` 的硬编码；根据帮助或版本选择参数，并兼容 JSON 默认输出 |
| P0 | 兼容新旧 fetch Schema | 同时支持 `data.content` 与 `data.document.content`；URL 缺失时基于可信输入 host 和 `document_id` 构造规范地址 |
| P0 | 统一 block ID 解析 | 在投影、章节构建、查找和序列化路径中统一支持 `id`、`block-id`、`block_id` |
| P0 | 为 S001 输出精确 span | 返回实际句子匹配文本或绝对起止偏移，使长句能够映射到 XML 文本节点 |
| P1 | 保留飞书 block 边界 | 在投影结果中加入不可与普通软换行混淆的边界，禁止 S001 跨独立 block 聚合 |
| P1 | 写后强制回读 | 将 update 返回的 revision 视为参考值；每次写入后 fetch 最新 revision、内容和 block ID |
| P1 | 增加真实 CLI 契约测试 | 引入 `lark-cli 1.0.93` 响应 fixture，覆盖嵌套 content、`id` 属性、缺失 URL 和滞后 revision |
| P2 | 改善 Node/NVM 诊断 | 报告当前 Node、NVM 版本和实际 CLI 路径，区分“未安装”和“安装在其他 Node 版本” |

## 8. 最终状态

本次确定可改的 6 条长句已经写回并通过复扫。文档当前不存在 S001 命中；剩余的“外部闭环”属于合理领域术语，无需处理。
