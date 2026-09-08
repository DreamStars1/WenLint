# Wenlint 飞书 CLI 兼容与 SourceMap 修复设计

状态：已批准实施

日期：2026-09-07

目标版本：Wenlint 0.2.x

依据：[Wenlint 飞书文档检查与写回报告](../../wenlint-feishu-review-2026-09-07.md)

## 1. 摘要

本次修复解决 Wenlint 0.2.0 与 `lark-cli 1.0.93` 的实际协议不兼容，并补齐 S001 超长句在飞书 XML 中的精确定位能力。

设计采用一个深模块：`LarkClient` 在真实外部依赖的 seam 上隐藏 CLI 方言、参数差异和 JSON Schema 差异。调用方只接收稳定的领域模型，不再理解 `lark-cli` 原始响应。飞书 XML 的 block ID 方言也在一个内部归一化入口处理，避免 `id`、`block-id` 和 `block_id` 判断散落。

修复完成后：

1. 旧版显式 `--format json` 和新版默认 JSON 两种 CLI 方言均可工作；
2. `data.content` 与 `data.document.content` 两种 fetch Schema 均可归一化；
3. `id`、`block-id`、`block_id` 均能形成正确 SourceMap 和章节定位；
4. S001 返回精确原文范围，单一可写文本节点中的长句可安全绑定；
5. 相邻飞书 block 不再被错误聚合为同一句；
6. 写回后的 fetch revision 始终是下一步唯一事实来源；
7. 缺失 CLI 时提供 Node/NVM 定位建议，但不自动安装、扫描或切换 Node。

## 2. 已观察到的问题

### 2.1 CLI 能力探测误报

`LarkClient.probe()` 把 `--format` 和 `json` 当作必备帮助文本。`lark-cli 1.0.93` 已默认输出 JSON并移除 `--format json`，因此被错误判为 `incompatible_cli`。

### 2.2 fetch Schema 漂移

旧测试 fixture 使用：

```json
{
  "data": {
    "document": {
      "document_id": "...",
      "revision_id": 1,
      "url": "https://example.feishu.cn/docx/..."
    },
    "content": "<p block-id=\"...\">...</p>"
  }
}
```

`lark-cli 1.0.93` 实际返回：

```json
{
  "data": {
    "document": {
      "content": "<p id=\"...\">...</p>",
      "document_id": "...",
      "revision_id": 1
    }
  }
}
```

当前 `inspection.py`、`patches.py` 和 `cli.py` 分别解析原始 mapping，导致相同兼容知识重复存在且一起失效。

### 2.3 XML block ID 方言漂移

当前投影和章节实现只识别 `block-id`、`block_id`。新版 CLI 的 XML 使用 `id`，造成：

- `Section.block_ids` 全为空字符串；
- `SourceSpan.block_id` 为 `None`；
- 普通词 finding 降级为 `synthetic_span`；
- S001 因空 match 降级为 `empty_match`；
- 安全 patch 无法生成。

### 2.4 S001 缺少精确范围

S001 只输出定位起点和 `sentence`，但 `match` 固定为空字符串。SourceMap 绑定需要精确的非空原文范围，因此 S001 永远不可写。

### 2.5 飞书 block 边界丢失

XML 投影目前只在顶层 block 间插入一个换行。`_collect_paragraphs()` 会把连续 paragraph 行当作 Markdown 的软换行段落，因此两个独立飞书 `<p>` 可能被拼成一个长句。

### 2.6 update revision 不是可靠快照

真实 CLI 的部分 update 响应会回显写入前 revision。下一次操作必须使用重新 fetch 得到的 revision，不能信任 update receipt 中的 revision。

### 2.7 Node/NVM PATH 诊断不足

当前进程可能优先命中 Codex 内置 Node，而 `lark-cli` 安装在另一个 NVM Node 版本中。此时错误只显示 executable missing，无法区分“未安装”和“未进入当前 PATH”。

## 3. 目标

- 支持已验证的 legacy CLI 方言和 `lark-cli 1.0.93` 方言。
- 把所有 CLI 参数与响应兼容逻辑集中到 `LarkClient` implementation。
- 让 inspect/apply 只依赖归一化领域模型。
- 保持现有超时、输出上限、环境白名单和错误脱敏约束。
- 让现代 `id` 属性参与投影、章节、fingerprint、查找、序列化和 patch 重映射。
- 为 S001 生成与输入文本精确相等的非空 span。
- 保持本地 Markdown 手动软换行的跨行长句检测行为。
- 保持飞书安全写回的精确匹配、章节批准和失败关闭语义。
- 增加新旧协议的离线契约测试，不依赖真实飞书环境。

## 4. 非目标

- 不自动安装或升级 `lark-cli`、Node、NVM、Wenlint。
- 不自动切换用户的 Node 版本。
- 不读取凭证目录，不扩大 OAuth scope。
- 不在测试中访问真实飞书文档或网络。
- 不放宽 `str_replace`、`overwrite`、模糊匹配或 revision 冲突限制。
- 不改变 KEEP / REWRITE / VERIFY / ASK 的职责划分。
- 不把飞书协议兼容逻辑加入通用 `wenlint` scanner。
- 不为了保留旧内部实现而增加第二层 pass-through adapter。

## 5. 架构原则

`lark-cli` 是 true external dependency。生产实现和离线 fake 是两个实际 adapter，因此 seam 成立。

外部 seam 的 interface 必须小而稳定：

```text
inspect/apply
    │
    ▼
DocumentGateway interface
    ├─ fetch(ref) -> FetchedDocument
    └─ replace_block(...) -> UpdateReceipt
            │
            ▼
LarkClient adapter
    ├─ CLI 能力探测与方言选择
    ├─ 受限子进程执行
    ├─ JSON 校验与错误脱敏
    └─ 新旧 Schema 归一化
            │
            ▼
        lark-cli
```

调用方不能再读取 `payload["data"]`。删除 `LarkClient` 后，CLI 方言与 Schema 复杂度应重新出现在多个调用方；这说明该深模块提供了真实 locality 和 leverage。

## 6. 领域模型与 interface

在 `wenlint/feishu/models.py` 增加不可变模型：

```python
@dataclass(frozen=True)
class FetchedDocument:
    ref: DocumentRef
    revision_id: int
    xml: str


@dataclass(frozen=True)
class UpdateReceipt:
    result: Literal["success"]
    reported_revision_id: int | None
    warnings: tuple[object, ...]
```

`FetchedDocument.ref` 必须已经解析到真实 `document_id` 和 canonical Docx URL。`xml` 是已通过大小和响应 Schema 门禁的完整 XML，但仍由 `project_xml()` 负责 DTD/ENTITY 和结构安全验证。

`UpdateReceipt.reported_revision_id` 仅用于诊断，不能作为后续写入基准。`warnings` 必须保留供 apply 汇报和回读验证。

可以使用一个仅含两种操作的内部 `Protocol` 表达 `DocumentGateway`，但不得把 CLI 方言、JSON mapping 或 capability 对象暴露到此 interface。生产 `LarkClient` 和测试 fake 均满足该 interface。

`probe()` 可以保留为显式诊断入口，但 capability 结果必须缓存在 `LarkClient` 内部；调用方不根据 probe 结果拼参数。

## 7. CLI 方言协商

新增私有不可变 `_CliCapabilities`，至少记录：

```python
@dataclass(frozen=True)
class _CliCapabilities:
    version: str
    json_args: tuple[str, ...]
```

探测规则：

1. `docs +fetch --help` 必须包含 `--doc`、`--doc-format`、`xml`、`--detail`、`full`、`--as`、`user`。
2. `docs +update --help` 必须包含 `block_replace`、`--block-id`、`--content`、`--doc-format`、`xml`、`--revision-id`、`--as`、`user`。
3. 如果 fetch/update 帮助均明确支持 `--format` 和 `json`，`json_args=("--format", "json")`。
4. 如果没有 `--format`，`json_args=()`，依赖默认 JSON 输出；实际 stdout 仍必须经过严格 JSON 和 `ok is True` 校验。
5. fetch 和 update 的 JSON 方言不一致时失败关闭，错误列出具体不一致能力。
6. 不以版本号大小判断兼容性。

`fetch()` 和 `replace_block()` 只能从缓存的 capability 构建 argv。禁止调用方自行追加 `--format json`。

## 8. fetch 响应归一化

`LarkClient.fetch(ref)` 完成以下归一化并返回 `FetchedDocument`：

1. 要求顶层 `ok is True`。
2. 要求 `data.document` 为 mapping。
3. 内容按以下顺序读取：
   - `data.document.content` 是非空字符串时使用；
   - 否则使用非空字符串 `data.content`；
   - 两者同时存在且内容不同则失败关闭，错误 kind 为 `ambiguous_content`。
4. `document_id` 必须是非空字符串。
5. `revision_id` 必须是正整数且不能是 bool。
6. canonical URL：
   - 有 `document.url` 时继续使用 `resolve_fetched_docx_ref()` 严格验证；
   - 缺少 URL 时，从已经通过 `parse_document_ref()` 校验的输入 host 与 `document_id` 构造 `https://<trusted-host>/docx/<document_id>`，再交给同一个解析函数验证；
   - 不采用响应中其他未经验证的 host 或 URL。
7. 返回已解析 `DocumentRef`、revision 和 XML。

`inspection.inspect_document()`、`patches._fetch_snapshot()` 和 CLI apply 的文档解析逻辑全部删除，改为消费 `FetchedDocument`。

## 9. update 响应归一化

`replace_block()` 保持以下写入约束：

- 只允许 `block_replace`；
- 必须提供正 revision；
- XML、URL、block ID 均作为独立 argv 元素；
- 顶层 `ok is True`；
- `data.result` 必须为 `success`；
- `partial_success` 与 `failed` 继续失败关闭。

成功时返回 `UpdateReceipt`：

- `reported_revision_id` 允许为空、旧值或新值；
- `warnings` 缺失时归一化为空 tuple；
- warnings 非空时 apply 必须汇报并完成写后 fetch 验证。

`apply_approved_section()` 在每个写入组后必须调用 `fetch()`。下一步 revision、block ID、章节 fingerprint 和 patch remap 只能来自该 fetch 结果。

## 10. XML block ID 归一化

新增内部纯函数模块 `wenlint/feishu/xml_protocol.py`，作为飞书 XML 方言的唯一知识入口：

```python
def block_id_of(element: Element) -> str | None:
    """Return one unambiguous block id from id/block-id/block_id."""
```

规则：

1. 接受非空 `id`、`block-id`、`block_id`。
2. 没有任何值时返回 `None`。
3. 多个属性存在但值相同，返回该值。
4. 多个属性值冲突时抛出稳定的协议错误，禁止按优先级静默选择。

以下位置全部复用该函数：

- 顶层投影生成 SourceSpan；
- 章节 heading 与 block ID 收集；
- `find_block()`；
- `serialize_block()` 与 patch 重映射依赖的查找；
- fingerprint 的易变属性处理。

`id`、`block-id`、`block_id` 全部属于 fingerprint 的易变属性。只改变 ID 方言或 ID 值不能改变章节 fingerprint。

模块只处理外部 XML 方言，不负责章节规则、投影或 patch 业务，因此调用方无需知道属性名称。

## 11. S001 精确 span

S001 finding 不再使用空 `match`。对每个超长句：

1. 在聚合段落中计算去除前导和尾随空白后的精确起止偏移；
2. 从原始输入文本中切出该范围，保持换行和标点；
3. `match` 设置为该精确子串；
4. `sentence` 使用同一可读文本；
5. `line`、`col` 指向 `match` 的第一个字符；
6. 本地 CLI 的 JSON `text` 因此变为非空长句原文，这是有意的兼容扩展；其他规则不变。

若句子跨多个 XML 文本节点，`bind_findings()` 继续给出 `cross_node` 并禁止自动写回。若完整句子位于单一可写节点，必须得到 `mapping_status="exact"` 和 `writable=true`。

不得通过模糊匹配或只保存句首片段来绕过精确范围验证。

## 12. 飞书 block 边界

`project_xml()` 在相邻顶层 block 之间插入两个换行，而不是一个换行。第二个换行仍为 synthetic span。

效果：

- 飞书相邻 `<p>` 被 scanner 识别为两个段落；
- 单个飞书 `<p>` 内的软换行或 `<br>` 仍可作为同一段落分析；
- 本地 Markdown 文件中的连续非空软换行行为保持不变；
- 标题、表格和资源块的排除规则保持不变。

不能通过全局修改 `_collect_paragraphs()` 禁止跨行聚合，否则会破坏本地 Markdown 的设计行为。

## 13. Node/NVM 诊断

缺失 executable 时，错误 details 增加安全且通用的 hint：

```text
Ensure the Node version containing lark-cli is active, or set WENLINT_LARK_CLI to its executable path.
```

允许报告当前请求的 executable 名称和 `PATH` 查找失败，不允许：

- 递归扫描用户目录；
- 自动调用 `nvm use`；
- 自动安装或升级 CLI；
- 输出完整 PATH、环境变量或凭证位置。

README 和 Skill 飞书参考应加入一个简短的 NVM 排查示例，但不能假设固定版本号或用户目录。

## 14. 测试设计

### 14.1 CLI 契约测试

扩展 fake CLI，支持 legacy/modern 两种模式：

- legacy help 含 `--format json`，argv 必须携带该参数；
- modern help 不含 `--format`，argv 禁止携带该参数；
- 两种模式均返回成功的 `FetchedDocument`；
- modern fetch fixture 使用 `data.document.content`、`id` 且无 URL；
- 两种 content 路径同时存在且不一致时失败关闭；
- 缺 document ID、无效 revision、非 JSON、`ok=false` 保持失败关闭；
- update 缺 warnings 时归一化为空；
- update 返回旧 revision 时，apply 仍使用后续 fetch 的新 revision。

### 14.2 XML 与章节测试

- 相同 XML 分别使用 `id`、`block-id`、`block_id`，投影、章节和 SourceMap 结果等价；
- ID 值变化或属性方言变化不改变 fingerprint；
- 冲突 ID 属性失败关闭；
- `find_block()` 可查找三种属性；
- modern `id` finding 能绑定到正确章节和 block URL。

### 14.3 S001 测试

- S001 的 `match`/公开 `text` 非空并精确等于输入子串；
- 单个简单 `<p id="...">` 中的长句可绑定且 writable；
- 含多个富文本节点的长句安全降级为 `cross_node`；
- 两个各自低于阈值的相邻飞书 `<p>` 不被合并成一条 S001；
- 本地 Markdown 的连续软换行仍会聚合并发现长句；
- 行号、列号和多行 match 保持精确。

### 14.4 写回测试

- 每个成功 block update 后都会 fetch；
- update 回显旧 revision 不影响下一次写入；
- 下一次写入使用 fetch 返回的新 revision 和新 block ID；
- warnings 被保留并在验证后标记；
- revision 冲突、章节变化、部分失败行为不回归。

## 15. 文档更新

更新以下内容：

- README 的飞书依赖与 NVM 排查；
- `references/feishu.md` 的 CLI 兼容说明；
- 原 0.2 设计中硬编码 `--format json` 的段落，改为“由 adapter 根据能力选择”；
- 记录已离线验证的 CLI 方言，不把版本号写成唯一兼容条件。

不得把本次真实飞书 URL、document ID、正文或 block ID加入测试 fixture 或提交内容。

## 16. 实施顺序

1. 增加领域模型与现代协议 fixture。
2. 深化 `LarkClient`：能力缓存、参数协商、fetch/update 归一化。
3. 迁移 inspect、apply 和 patches，删除调用方原始 mapping 解析。
4. 增加 XML ID 归一化并迁移所有使用点。
5. 实现 S001 精确 match。
6. 在飞书投影中加入硬 block 边界。
7. 完善 revision/warnings 测试与 NVM 错误提示。
8. 更新 README、Skill reference 和旧设计文档。
9. 运行完整测试与打包检查。

## 17. 验收标准

- `wenlint-feishu inspect` 能消费 modern fixture，无兼容层脚本。
- legacy fixture 和全部既有本地 Wenlint 行为通过。
- modern XML 的 sections 不含空 block ID。
- 简单段落中的 S001 finding 为 `exact`、`writable=true`。
- 相邻飞书 block 不产生跨 block S001；本地 Markdown 软换行测试仍通过。
- inspect/apply/patches 中不存在 `payload.get("data")` 一类 CLI Schema 解析。
- update revision 只作诊断，写后 fetch 是后续状态唯一来源。
- 现有安全限制、退出码和隐私测试全部通过。
- 完整 `pytest` 通过。
- wheel 和 sdist 构建成功，并在干净环境验证 `wenlint`、`wenlint-feishu`、`wenlint-feedback` 入口。
- `git diff` 不包含真实飞书正文、URL、token、document ID 或 block ID。
- 不修改或删除 `docs/wenlint-feishu-review-2026-09-07.md`。

## 18. Cursor 实施约束

Cursor 只在 `D:\wenlint\WenLint` 工作区内操作，并必须：

- 先检查 git 状态，保留所有现有工作；
- 按本 spec 实现，不访问真实飞书或其他外部系统；
- 添加有行为价值的测试，并运行相关测试与完整测试；
- 不 reset、clean、stash、commit、push 或创建 PR；
- 不修改本 spec 和现有检查报告，除非修正文档链接所必需；
- 不使用 `--force`；
- 最后报告修改文件、测试命令、结果和剩余不确定性。
