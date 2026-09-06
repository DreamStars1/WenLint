# WenLint 飞书文档与 Codex Skill 集成设计

状态：设计讨论已批准，等待书面复核

日期：2026-09-06

目标版本：WenLint 0.2

## 1. 摘要

WenLint 0.2 将保持现有本地检查行为和“核心只发现、不改写”原则。新版本增加飞书 Docx/Wiki 文档检查能力，并通过 Codex Skill 完成语义判断、逐章人工确认和安全写回。

第一阶段的交付边界是：

1. 共享的确定性 WenLint 规则核心；
2. 独立的 `wenlint-feishu` 命令和 Python 飞书适配层；
3. 可通过 GitHub / `npx skills` 分发的 Codex Skill；
4. 对飞书正文执行“总览 → 逐章确认 → 局部写回 → 回读重扫”的完整流程。

面向 Web/App 的独立 Agent 不在本设计中实现。它未来复用同一 Python 核心和飞书适配层，但采用全局 diff 一次确认的交互模型，并单独设计。

## 2. 背景与问题

当前 WenLint 只接受本地 Markdown、文本和 reStructuredText 文件。它已经具备稳定的规则发现、Markdown 结构保护和 JSON 输出。它还无法直接处理团队日常使用的飞书文档。

简单地把飞书文档导出为 Markdown 再扫描存在三个问题：

- Markdown 行列与飞书 block 不是稳定的一一映射，无法安全写回；
- 文档中重复句、富文本节点和协作编辑会使模糊定位写错位置；
- Skill 的安装不等于 Python 运行时的安装，必须分别设计分发和依赖检查。

因此本设计以飞书 XML 快照为唯一结构事实来源。适配层从 XML 生成供现有 scanner 使用的确定性分析投影，并保留从投影字符到 XML 文本节点的精确 SourceMap。任何不能精确映射或不能验证的建议只报告，不自动写入。

## 3. 目标

- 支持飞书 `/docx/` 和 `/wiki/` URL；Wiki 在读取时解析到实际 Docx。
- 使用用户已安装、已授权的 `lark-cli` 读取和更新文档。
- 复用现有 `scan_text` 规则语义，不为飞书维护第二套规则引擎。
- 为每条 finding 提供章节和飞书 block 定位。
- 由 Skill 对 finding 做 KEEP / REWRITE / VERIFY / ASK 四分类。
- 在写回前先给出全局摘要，再逐章请求用户确认。
- 每次写操作前后都基于最新快照验证，协作者改动不会被静默覆盖。
- 保持本地 `wenlint <path>` 的 CLI 和 JSON 行为兼容。
- 支持 PyPI/pipx 分发 Python 引擎，以及 GitHub/`npx skills` 分发 Skill。

## 4. 非目标

- 不实现 Web/App 前端或面向 Web/App 的独立 Agent。
- 不处理飞书 Sheets、Slides、Base、妙记或评论写入。
- 不自动申请 OAuth、保存 token、读取 `lark-cli` 凭证目录或接收 app secret。
- 不执行全文覆盖，不提供模糊匹配、强制写入或冲突后静默重试。
- 不自动修改表格、代码块、同步块、资源块或跨多个富文本节点的内容。
- 不让 WenLint 核心决定语义修改，也不在核心中调用 LLM。
- 不由 `npx skills` 安装或管理 Python 运行时。

## 5. 已确定的产品决策

| 议题 | 决策 |
| --- | --- |
| 当前产品形态 | 共享核心 + Codex Skill + 飞书逐章确认；Web/App Agent 后续单独设计 |
| 飞书认证 | 复用预装、已授权的 `lark-cli`，显式使用 user 身份 |
| 支持的链接 | `/docx/`、`/wiki/`；Wiki 解析为 Docx |
| 结构事实来源 | XML `full` 单快照，不使用 Markdown/XML 双快照和模糊对齐 |
| 人工检查点 | 先展示总览，再逐章批准、排除个别项、跳过或停止 |
| 写回位置 | 用户确认后直接写回原飞书正文 |
| 并发策略 | 目标章节未变可继续；目标章节变化则重扫并重新确认 |
| CLI 入口 | 新增独立 `wenlint-feishu`，不占用 `wenlint feishu` 路径语义 |
| 失败策略 | 默认停止，不猜位置，不自动回滚，不宣称未验证的成功 |
| Python 版本 | 最低 3.11；推荐开发 3.13；CI 覆盖 3.11、3.13、3.14 |
| 分发 | Python 引擎走 PyPI/pipx；Skill 走 GitHub/`npx skills` |

## 6. 用户体验

### 6.1 只读检查

当用户说“检查、评估、审查这个飞书文档”而未要求修改时，Skill：

1. 识别 Docx/Wiki URL；
2. 检查 `wenlint-feishu` 和 `lark-cli` 是否可调用；
3. 读取 XML 快照并运行 WenLint；
4. 对每条 finding 做四分类；
5. 按章节展示问题、判断、依据状态和修改建议；
6. 不调用任何飞书更新命令。

“给我修改方案”或“给我 diff”仍属于只读路径。

### 6.2 请求直接修改

当用户明确要求“修复、修改、应用、直接写回正文”时，Skill：

1. 完成全文扫描和四分类；
2. 展示总览，包括章节数、各分类数量、可安全自动写回数量和只报告数量；
3. 按文档顺序一次只展示一个章节；
4. 对该章提供四个动作：
   - 批准本章全部可写 patch；
   - 排除用户指定的 patch 后批准其余项；
   - 跳过本章；
   - 停止本次任务；
5. 未得到明确批准时不写入该章；
6. 对批准章节执行局部写回、逐次回读和最终重扫；
7. 汇报已应用、未应用、需重新确认和仍待处理的项目。

VERIFY 只有在找到用户允许使用的依据后才能转为 REWRITE。ASK、KEEP 和定位不确定项永不进入自动写回。

### 6.3 章节定义

“章节”按标题层级确定：一个标题 block 及其后直到下一个同级或更高级标题之前的内容构成一章。第一个标题前的内容属于合成章节“文档开头”。没有标题的文档整体视为一章。

章节确认是 Skill 的对话责任，不由非交互式 Python CLI 自行读取 stdin 提问。

## 7. 总体架构

```text
用户
  │
  ▼
Codex WenLint Skill
  ├─ 识别意图与输入来源
  ├─ KEEP / REWRITE / VERIFY / ASK
  ├─ 生成受约束的候选 patch
  └─ 总览与逐章人工确认
          │
          ▼
wenlint-feishu 适配层
  ├─ lark-cli 子进程协议
  ├─ Docx/Wiki 解析
  ├─ XML → 分析投影 + SourceMap
  ├─ 快照、章节、冲突与 patch 校验
  └─ 已批准 patch 的局部 block_replace
          │
          ├────────► WenLint scan_text（只发现）
          │
          ▼
      lark-cli ────► 飞书 Docx
```

职责边界：

- `wenlint` 核心继续只发现候选，不生成 replacement，不访问飞书。
- `wenlint-feishu` 负责 I/O、结构映射、校验和执行已批准 patch；它不判断文意。
- Skill 负责语义判断、查证、生成改写、请求人工确认和编排命令。
- `lark-cli` 负责身份、权限、Docx/Wiki OpenAPI 和 block 更新。

## 8. 模块设计

建议新增以下模块，不把飞书逻辑塞入现有 `wenlint/cli.py`：

```text
wenlint/
├── cli.py                 # 现有本地 CLI，保持兼容
├── scanner.py             # 现有确定性规则核心
└── feishu/
    ├── cli.py             # wenlint-feishu 入口
    ├── lark.py            # lark-cli 受限子进程适配器
    ├── document.py        # URL/Wiki/快照模型
    ├── projection.py      # XML → 分析投影 + SourceMap
    ├── sections.py        # 章节划分、定位器和 fingerprint
    ├── findings.py        # finding → source span/章节绑定
    └── patches.py         # patch 校验、合并、应用与结果状态
```

核心模型使用不可变 dataclass 或等价只读对象：

```python
@dataclass(frozen=True)
class DocumentRef:
    input_url: str
    kind: Literal["docx", "wiki"]
    input_token: str
    document_id: str | None
    canonical_url: str | None

@dataclass(frozen=True)
class SourceSpan:
    projection_start: int
    projection_end: int
    block_id: str | None
    node_path: tuple[int, ...] | None
    source_start: int
    source_end: int
    writable: bool

@dataclass(frozen=True)
class Section:
    locator: str
    title: str
    level: int
    block_ids: tuple[str, ...]
    fingerprint: str

@dataclass(frozen=True)
class DocumentSnapshot:
    ref: DocumentRef
    revision_id: int
    xml: str
    projection: str
    source_map: tuple[SourceSpan, ...]
    sections: tuple[Section, ...]

@dataclass(frozen=True)
class Patch:
    patch_id: str
    section_locator: str
    section_fingerprint: str
    block_id: str
    node_path: tuple[int, ...]
    before: str
    after: str
    rule_id: str
    rationale: str

@dataclass(frozen=True)
class ApprovedSectionPlan:
    document_id: str
    section_locator: str
    initial_fingerprint: str
    approved_patch_ids: tuple[str, ...]
    expected_fingerprints: tuple[str, ...]
```

解析 URL 时，`document_id` 和 `canonical_url` 可以尚未解析。首次 fetch 必须返回一个新 `DocumentRef`，其中这两个字段均为非空的实际 Docx 值；`DocumentSnapshot` 和所有写操作只接受已解析引用。实现可以增加字段，但不得削弱精确定位、原文比较、章节 fingerprint 或用户批准状态。

### 8.1 Python 注释与 docstring 规范

本版本新增或实质修改的 Python 模块、类、函数和方法使用 Google Style docstring：

- 模块 docstring 说明职责和边界，不复述文件名；
- 公共类、函数和方法必须有 docstring；私有函数在行为、约束或失败语义不直观时也必须有 docstring；
- 按实际签名使用 `Args:`、`Returns:`、`Raises:`、`Yields:` 和 `Attributes:`，无对应内容时不保留空章节；
- 首行使用祈使语气概述行为，复杂契约在空行后的段落说明；
- 行内注释解释安全原因、协议限制或不明显的设计取舍，不逐句翻译代码；
- dataclass 字段含义不能从类型和字段名直接判断时，在类 docstring 的 `Attributes:` 中说明；
- 测试函数可以省略 docstring，但测试名必须表达场景和预期结果；
- 所有 docstring 和注释必须与实际退出码、超时、大小限制、并发语义和失败关闭行为一致。

验收时对 `wenlint/feishu/`、修改过的现有 Python 文件和新增测试 helper 做人工 docstring 审查。缺失、过时或仅复述代码的注释视为验收失败。

## 9. `lark-cli` 契约

### 9.1 能力门禁

本设计不虚构一个数字版最低版本，而采用能力门禁。兼容的 `lark-cli` 必须同时支持：

- `docs +fetch`；
- `docs +update`；
- `--doc-format xml --detail full`；
- `/wiki/` 到实际文档的解析；
- `--as user`；
- JSON 顶层 `ok`、文档 `revision_id` 和更新结果字段；
- 带 `--revision-id` 的 `block_replace`。

缺任一能力即失败关闭，并显示缺失能力和检测到的 CLI 版本。发布时记录通过适配器合约测试的版本集合，但运行时以能力而非版本字符串判断兼容性。

### 9.2 读取

适配器执行等价的 argv：

```text
lark-cli docs +fetch
  --doc <URL-or-token>
  --doc-format xml
  --detail full
  --as user
  --format json
```

不单独执行 `auth status --verify` 作为预检。首次实际 fetch 同时完成鉴权和 scope 检查。若返回认证或权限错误，再给出对应恢复指引。这样检查的是当前操作真正需要的权限。

### 9.3 更新

自动写回只使用局部 `block_replace`：

```text
lark-cli docs +update
  --doc <canonical-docx-url-or-token>
  --command block_replace
  --block-id <latest-block-id>
  --content <complete-patched-block-xml>
  --doc-format xml
  --revision-id <latest-revision>
  --as user
  --format json
```

不使用 `str_replace`。它执行全文字符串匹配，遇到重复文本会产生误改风险。不使用 `overwrite`，因为它会引入丢失评论和暂不支持资源的风险。

### 9.4 子进程安全和资源上限

- 使用 argv 数组和 `shell=False`，URL、token、XML 都只作为单个参数值传递。
- stdin 设为 `DEVNULL`，禁止等待交互输入。
- fetch 默认超时 60 秒，单次 update 默认超时 30 秒；CLI 允许调用方降低但不能取消超时。
- stdout 上限 20 MiB，stderr 上限 1 MiB；超限立即停止，不解析截断结果。
- XML 输入上限 20 MiB，拒绝 DTD 和 ENTITY，使用禁止外部实体的解析器。
- 不继承或打印完整环境变量，不记录完整 stdout、stderr 或文档正文。
- 进程退出码必须为 0，且 JSON 顶层 `ok` 必须为 `true`；任一条件不满足都视为失败。
- update 还必须满足 `data.result == "success"`。`partial_success` 和 `failed` 都停止后续写入。
- `warnings` 非空时即使成功也必须展示并回读验证。

## 10. XML 分析投影与 SourceMap

### 10.1 单一结构事实来源

读取只获取一次 XML `full` 快照。Markdown 不参与定位，也不与 XML 进行二次模糊配对。

为了复用现有 Markdown-aware scanner，适配层从 XML 生成确定性的“分析投影”。投影类似 Markdown，但只是内存中的扫描坐标系：

- `h1` 至 `h9` 生成对应数量的 `#` 和标题文字，使现有 scanner 跳过标题规则；
- `p` 生成正文行；
- `li` 生成 `- ` 或有序列表前缀；
- `blockquote` 生成 `> ` 前缀；
- `checkbox` 生成列表式前缀；
- 行内 `b/em/u/del/span/a` 只投影可见文字；链接 URL 不进入可扫描文本；
- `pre/code`、表格和资源块生成不可扫描的结构占位或空行；
- 每个顶层 block 之间至少有一个确定性换行边界。

投影添加的 `#`、列表符号、引用符号和换行记为 synthetic span，不可写。来自 XML 文本节点的每个字符都映射到 `block_id`、节点路径和节点内偏移。

### 10.2 支持与降级

第一版可扫描且具备写回资格的正文位于简单 `p`、`li`、`blockquote`、`checkbox` 或 callout 内的简单文本节点。

以下内容可以保留在章节上下文中，但不自动写回：

- `pre/code`、table、grid、同步块；
- `img`、`source`、`whiteboard`、`sheet`、`bitable`、`cite` 等 token 化资源；
- finding 或改写范围跨多个文本节点；
- 无法唯一映射到一个可写 block 和文本节点的内容。

定位失败不影响其他 finding 的只读报告，但该 finding 的 `writable` 必须为 `false`。

### 10.3 finding 绑定

scanner 的行列先转换为投影中的全局字符范围，再通过 SourceMap 绑定到来源：

1. finding 起止字符必须全部落在真实来源 span 中；
2. 所有字符必须属于同一 block 和同一 XML 文本节点；
3. XML 节点中的精确原文必须等于 finding 的 `match`；
4. 映射必须唯一；
5. 所在 block 必须属于唯一章节。

任一条件失败时记录明确原因，例如 `synthetic_span`、`cross_node`、`duplicate_source`、`unsupported_block` 或 `unmapped`，不得用文本相似度补救。

## 11. 章节定位与变更检测

每个章节生成结构定位器和 fingerprint：

- 定位器由标题路径和同名兄弟序号组成；“文档开头”使用固定保留值；
- fingerprint 是章节规范化 XML 的 SHA-256；
- 规范化时排除 revision、block ID 等易变标识，但包含可见文本、标签层级、影响语义的属性和资源引用；
- 完全相同且无法唯一定位的重复章节视为冲突，不猜测。

这个策略允许协作者修改其他章节后继续处理当前章节，同时能识别目标章节自身的任何文本或结构变化。

## 12. 四分类与 patch 生成

四分类语义保持现有 Skill 约定：

| 分类 | 含义 | 可进入写回 |
| --- | --- | --- |
| KEEP | 合理用法或误报 | 否 |
| REWRITE | 可根据当前上下文确定修改 | 是，仍需章节批准和结构校验 |
| VERIFY | 需要先查允许的数据源 | 找到依据后可转为 REWRITE |
| ASK | 资料不足，必须问作者 | 否 |

候选 patch 必须：

- 关联一个 WenLint finding；
- 只替换一个可写 XML 文本节点中的精确连续原文；
- 携带 `before`、`after`、规则、理由、章节定位器和章节 fingerprint；
- 保留节点外的标签、属性、样式和资源引用；
- 不与同一 block 内其他 patch 的来源范围重叠；
- 不把事实性不确定表达改成未经证实的确定陈述。

同一 block 的多个不重叠 patch 在内存中合并为一个完整 patched block XML，并通过一次 `block_replace` 写入。重叠 patch 整组降级为需人工处理。

## 13. 人工确认协议

Skill 在任何写入前先输出全局摘要，然后逐章进行检查点。每章应展示：

- 章节标题和顺序；
- 每个 patch 的编号、规则、原文、建议文本和理由；
- VERIFY 的依据或 ASK 的缺口；
- 不可自动写回项及原因；
- 本章批准后预计更新的 block 数量。

用户可以批准整章、拒绝整章，或排除章内个别修改。未明确批准的 patch 一律不写回。每章写回结束后再询问下一章，而不是预先把尚未确认章节全部写入。 :codex-annotation{index="1"}

批准记录只在当前任务内存中有效，绑定到文档 ID、章节定位器、章节 fingerprint 和 patch 内容。批准集合还保存按 block 写入后的预期章节 fingerprint。未被本次批准覆盖的文档变化、patch 内容变化或任务重启都会使原批准失效。

## 14. 安全写回算法

对每个获批章节执行：

1. 全量重新 fetch 最新 XML `full` 快照。
2. 用结构定位器查找目标章节；要求唯一匹配。
3. 比较最新章节 fingerprint 与用户批准时的 fingerprint。
4. 若 fingerprint 不同：不写入，基于最新章节重新扫描、重新分类并重新确认。
5. 若 fingerprint 相同：把获批 patch 重新映射到最新 block ID 和节点路径。
6. 对每个待更新 block，再次验证：
   - block 存在；
   - 原文精确相等；
   - 来源范围唯一；
   - patched XML 合法；
   - 没有修改未批准节点、属性或资源引用；
7. 使用最新 revision 执行一次 `block_replace`。
8. 若 update 返回 revision 冲突，重新 fetch 并比较当前章节与本轮写入前的预期 fingerprint。章节未变时使用新 revision 和新 block ID 重试；连续两次 revision 冲突后停止。章节已变时转入重新扫描和确认。
9. 成功写入后立即重新 fetch 最新快照，不沿用旧 block ID。
10. 验证目标 block 的预期文本、结构和本次写入后的预期章节 fingerprint，并重映射本章剩余 patch。
11. 除第 8 步的受限 revision 冲突重试外，任一步失败都停止本章及之后的写入，并输出部分结果。
12. 章节全部写完后，在最新全文上重新运行 WenLint。

其他章节发生变化不阻止当前章节继续；目标章节发生任何规范化内容变化则必须重扫和重新确认。

不自动回滚已经成功的 block。回滚会引入覆盖协作者后续修改的风险。部分失败时报告已应用 patch、未应用 patch、最新 revision、失败原因和需要重新确认的章节。

## 15. CLI 设计

新增独立脚本入口：

```toml
[project.scripts]
wenlint = "wenlint.cli:main"
wenlint-feishu = "wenlint.feishu.cli:main"
```

不用 `wenlint feishu`，因为当前 `wenlint` 的第一个位置参数是本地路径；名为 `feishu` 的真实文件或目录必须继续可被扫描。

### 15.1 检查命令

```text
wenlint-feishu <docx-or-wiki-url> --json [--profile PROFILE]
wenlint-feishu inspect <docx-or-wiki-url> --json [--profile PROFILE]
```

第一种是第二种的快捷形式。默认不写入。JSON 在现有 finding 字段外增加 `source`、`section` 和 `location`，本地 `wenlint --json` 的既有 schema 不变。

### 15.2 应用命令

```text
wenlint-feishu apply <docx-or-wiki-url> --patch-file <path> --json
```

`apply` 是供 Skill 编排的受约束执行器，只接受包含文档 ID、基础 revision、章节 fingerprint、批准 patch ID 和精确 before/after 的 JSON manifest。它仍会执行第 14 节全部校验；manifest 不是跳过人工确认或冲突检查的后门。

patch 文件必须位于当前任务工作目录。Skill 使用专用临时文件，并在结束、失败或取消时清理它；CLI 不删除调用方传入的任意文件。stdout 只输出状态和最小定位信息，不回显全文或完整 patched XML。

### 15.3 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 命令成功；inspect 是否有 finding 由 JSON 内容表达 |
| 1 | `--fail-level` 门禁触发 |
| 2 | 输入或 patch manifest 无效 |
| 3 | `lark-cli` 缺失、能力不兼容、认证、权限或网络错误 |
| 4 | revision、章节、block 或原文冲突，零新增写入 |
| 5 | 本次 apply 已有部分写入后失败 |

## 16. JSON 协议

inspect 的顶层对象：

```json
{
  "ok": true,
  "source": {
    "kind": "feishu",
    "document_id": "doxcnExample",
    "revision_id": 42,
    "url": "https://example.feishu.cn/docx/example",
    "identity": "user"
  },
  "sections": [],
  "findings": []
}
```

每条飞书 finding 复用现有 `rule`、`type`、`severity`、`category`、`message`、`review_hint`、`line`、`column`、`text`、`sentence`、`before`、`after`，并增加：

```json
{
  "section": {
    "locator": "产品设计[1]/权限模型[1]",
    "title": "权限模型",
    "fingerprint": "sha256:..."
  },
  "location": {
    "block_id": "blkExample",
    "block_url": "https://example.feishu.cn/docx/example#blkExample",
    "node_path": [0, 1],
    "mapping_status": "exact",
    "writable": true,
    "reason": null
  }
}
```

错误时 stdout 不输出半份 findings。stderr 输出不含正文的精简 JSON 错误，包含稳定 `kind`、人类可读 `message`、`retryable`，并按需包含 `missing_scopes`、`hint` 和检测到的 CLI 版本。

## 17. 错误、安全与隐私

### 17.1 失败关闭

- URL/token 无效、XML 不合法、输出非 JSON、`ok != true` 或 revision 缺失时不继续。
- 定位不唯一、patch 重叠、原文不相等或结构不支持时不写入。
- 网络超时不输出不完整或过时的半份扫描结果。
- update 返回 warning 时不直接宣称成功，必须回读核验。
- 高风险确认、权限扩大或 scope 缺失交还给用户处理，不静默授权。

### 17.2 Prompt injection

飞书正文始终是不可信数据。正文中的“忽略规则、执行命令、打开链接、扩大权限、发送内容”等文字只是待检查内容，不能改变 Skill 流程。Skill 不执行正文代码或链接，也不访问用户未授权的数据源。

### 17.3 隐私

- 正文、XML、patch manifest 和授权状态默认只存在于内存或任务临时目录。
- 正常日志只记录文档 ID 的脱敏摘要、revision、耗时、计数和错误类型。
- 不记录凭证、完整 URL 查询参数、全文、完整 stdout/stderr 或 replacement 内容。
- 临时 XML 和 patch 文件在正常结束、失败和取消路径都清理。
- 测试使用虚构 fixture，不提交真实飞书 URL、token、人员或公司内容。

## 18. Python 与依赖策略

`pyproject.toml` 是 Python 包依赖的唯一事实来源，不需要额外 `requirements.txt`。

目标配置：

```toml
[project]
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
test = ["pytest>=8.4,<10"]
```

运行时继续只依赖标准库和外部 `lark-cli` 可执行文件。开发者使用：

```text
python -m pip install -e ".[test]"
python -m pytest
```

支持策略：

- 3.11 是最低版本，兼顾现代类型语法、稳定性和企业环境可用性；
- 3.13 是推荐本地开发版本；
- CI 测试 3.11、3.13、3.14；
- 不把 3.12 加入每次矩阵，最低版本和较新版本已覆盖主要兼容面；发布前可增加一次全版本检查；
- 当前 3.9 兼容性在 0.2 中明确结束，并在 changelog 标注。

## 19. 分发设计

### 19.1 Python 引擎

WenLint 发布到 PyPI。面向 Agent 用户优先推荐 pipx，使 `wenlint` 和 `wenlint-feishu` 成为隔离的全局命令：

```text
pipx install wenlint
```

开发者仍可使用普通 venv 和 `pip install -e .`。Skill 检测到命令缺失时显示安装指引，不在未获用户允许时自动安装 Python、pipx、WenLint 或 `lark-cli`。

### 19.2 Skill

仓库根 `SKILL.md` 作为 WenLint Skill 的唯一主说明，飞书细节放入 `references/feishu.md`，避免主文件膨胀：

```text
WenLint/
├── SKILL.md
└── references/
    └── feishu.md
```

用户可以通过 `npx skills` 从 GitHub 安装：

```text
npx skills add DreamStars1/WenLint
npx skills add DreamStars1/WenLint --skill wenlint --agent codex --global
```

第一条用于交互式选择安装位置；第二条用于明确安装 `wenlint` 到 Codex 的全局 Skill 目录。

`npx skills` 的公开发现协议明确支持仓库根 `SKILL.md`，因此 0.2 固定采用该单一来源。发布验收必须实际运行 `--list` 和 Codex 安装流程，确认 Skill 名称、引用文件和安装位置正确。

`npx skills` 只分发 Skill 文件，不安装 Python 引擎。Skill 首次运行时分别检查 `wenlint-feishu` 和 `lark-cli`，给出两个独立、可复制的恢复步骤。

### 19.3 后续 Plugin

OpenAI Plugin/MCP 可作为未来面向更广泛用户的封装，负责统一的依赖和工具暴露。它不属于 0.2 的交付条件，也不改变本设计的核心/适配层边界。

## 20. 测试策略

### 20.1 单元测试

- Docx/Wiki URL、token、锚点和 canonical URL 解析；
- XML 安全解析、标题、段落、列表、引用、链接、富文本和资源块；
- 分析投影的行列稳定性和 synthetic span；
- SourceMap 的单节点精确映射、重复文本、跨节点和不支持结构降级；
- 章节边界、同名标题序号、无标题文档和“文档开头”；
- fingerprint 忽略易变 block ID，但能检测文本、结构、属性和资源变化；
- patch 原文检查、范围检查、重叠拒绝和同 block 合并；
- DTD/ENTITY、非法 XML、20 MiB 边界和输出上限。

### 20.2 假 `lark-cli` 合约测试

在临时 PATH 放置可执行 stub，覆盖：

- fetch/update 成功；
- 非零退出码；
- 退出码 0 但 `ok=false`；
- `partial_success`、warnings 和 malformed JSON；
- timeout、stdout/stderr 超限；
- 未登录、缺 scope、权限不足、网络失败和 Wiki 解析失败；
- 实际 argv 使用 `--as user`、XML `full`、明确 revision 且不经过 shell；
- 含分号、反引号、`$()` 和换行的 URL/文本不会成为 shell 语法。

### 20.3 工作流测试

- 只读请求从不调用 update；
- 先总览、后按顺序逐章提问；
- 批准整章、排除个别项、跳过和停止；
- 未批准 patch 零写入；
- KEEP/ASK 和无依据 VERIFY 零写入；
- 其他章节变化时当前未变章节可继续；
- 当前章节变化时重扫并重新确认；
- 每个 block 写后重新 fetch、使用新 revision 和新 block ID；
- 中途失败正确区分已应用、未应用和需重新确认；
- 完成后全文重扫，不把回读失败报告成成功。

### 20.4 兼容与分发测试

- 现有 36 个回归测试保持通过；
- 本地 `wenlint <path>`、路径名 `feishu` 和既有 JSON schema 不回归；
- Python 3.11、3.13、3.14 CI 全部通过；
- wheel/sdist 在干净环境安装，两个 console script 可运行；
- 包元数据无未声明运行时依赖；
- 新增和实质修改的 Python 生产代码符合第 8.1 节 Google Style docstring 与注释规范；
- `npx skills` 能发现和安装 WenLint Skill，引用文件完整；
- Skill 中命令与 README、CLI `--help` 一致。

Live E2E 使用专门的临时飞书测试文档和人工授权，不进入无凭证的公共 CI。

## 21. 验收标准

满足以下条件才可标记 0.2 完成：

- 本地 WenLint 行为和现有测试不回归；
- `wenlint-feishu` 能用 user 身份读取 Docx 和 Wiki；
- XML 投影中的 finding 能精确绑定章节、block 和单一文本节点，或安全降级；
- 只读意图在所有测试中均为零写入；
- Skill 在写入前先给总览，并逐章取得明确批准；
- 用户可在章内排除个别 patch；
- 目标章节冲突触发重扫和重新确认，其他章节变化不会不必要地阻塞；
- 每次 block 写入后重新 fetch 和重映射；
- 从不使用全文 `str_replace`、`overwrite`、模糊匹配或强制写入；
- 部分失败报告准确，不自动回滚；
- 最终回读与重扫通过后才声称修改成功；
- Python 包可从 PyPI/pipx 安装，Skill 可由 GitHub/`npx skills` 安装；
- 安装 Skill 不会被误描述为已经安装 Python 或 `lark-cli`；
- Python 生产代码的 Google Style docstring 完整、准确且不复述实现；
- 临时正文和 patch 数据被清理，日志不泄露正文或凭证。

## 22. 实施顺序

在书面 spec 复核后，实施计划按以下依赖顺序拆分：

1. Python 版本和包元数据升级，建立 3.11/3.13/3.14 CI；
2. `lark-cli` 受限适配器与假 CLI 合约测试；
3. XML 投影、SourceMap、章节模型和只读 inspect；
4. patch manifest、冲突检测、局部 update 和回读；
5. Skill 的飞书路由、四分类和逐章检查点；
6. PyPI/pipx 与 `npx skills` 分发验收；
7. 临时文档 live E2E 和文档更新。

每一步都保持核心 `scan_text` 不依赖飞书，并在进入下一步前运行现有回归测试。

## 23. 参考资料

- [OpenAI：Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Vercel Labs skills CLI](https://github.com/vercel-labs/skills)
- [Python versions](https://devguide.python.org/versions/)
- [Lark CLI](https://github.com/larksuite/cli)
