# WenLint Feishu and Codex Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the WenLint 0.2 Feishu Docx/Wiki inspection and approved-patch writeback adapter, then expose its chapter-by-chapter safety workflow through the WenLint Codex Skill.

**Architecture:** Keep `wenlint.scan_text` deterministic and Feishu-independent. A new `wenlint.feishu` package owns the bounded `lark-cli` subprocess contract, XML analysis projection, SourceMap, section fingerprints, inspection JSON, and fail-closed patch application; the root Skill owns semantic classification and human approval.

**Tech Stack:** Python 3.11+ standard library, argparse, dataclasses, `xml.etree.ElementTree` with explicit DTD/ENTITY rejection, pytest 8.4+, external `lark-cli`, Markdown Skill files, GitHub Actions.

## Global Constraints

- Follow `docs/superpowers/specs/2026-09-06-wenlint-feishu-codex-skill-design.md` as the source of truth.
- Keep runtime `dependencies = []`; `lark-cli` remains an external executable.
- Support Python 3.11 and newer; recommend 3.13; CI runs 3.11, 3.13, and 3.14.
- Preserve existing `wenlint <path>` behavior and its JSON schema, including a local file or directory literally named `feishu`.
- Add only the separate `wenlint-feishu` console script.
- New or substantially modified Python production code uses accurate Google Style docstrings and reason-focused comments.
- Use argv arrays with `shell=False`; never execute document content, URLs, or patches as shell syntax.
- Never use Feishu `str_replace`, `overwrite`, fuzzy text matching, or `revision_id=-1` for writes.
- Read with XML `full` and explicit `--as user`; after every block write, fetch and remap again.
- No write occurs from inspect mode or without an explicit patch manifest.
- Do not push or publish packages. Local commits are allowed after each green task.

---

## File Map

| Path | Responsibility |
| --- | --- |
| `pyproject.toml` | Python floor, test extra, and console scripts |
| `.github/workflows/test.yml` | 3.11/3.13/3.14 CI matrix |
| `wenlint/feishu/__init__.py` | Stable public Feishu adapter exports |
| `wenlint/feishu/models.py` | Frozen domain models and JSON-safe result models |
| `wenlint/feishu/document.py` | Docx/Wiki parsing and canonical document references |
| `wenlint/feishu/lark.py` | Bounded, non-shell `lark-cli` adapter and error normalization |
| `wenlint/feishu/projection.py` | Safe XML parse, analysis projection, SourceMap, XML serialization |
| `wenlint/feishu/sections.py` | Section boundaries, locators, canonicalization, fingerprints |
| `wenlint/feishu/findings.py` | Scanner coordinate conversion and finding/source binding |
| `wenlint/feishu/inspection.py` | Fetch → project → scan → structured inspection orchestration |
| `wenlint/feishu/patches.py` | Manifest parsing, validation, block patching, retries, verification |
| `wenlint/feishu/cli.py` | `inspect` shortcut, `inspect`, and `apply` argparse routes |
| `tests/feishu/fixtures/*.json` | Fictional lark-cli responses only |
| `tests/feishu/fixtures/*.xml` | Fictional Docx XML only |
| `tests/feishu/test_*.py` | Unit, contract, inspection, writeback, and CLI tests |
| `tests/test_skill_contract.py` | Static safety and distribution contract for Skill docs |
| `SKILL.md` | Short source router and six-step WenLint workflow |
| `references/feishu.md` | Detailed Feishu inspect/approval/writeback instructions |
| `README.md` | Python/pipx and `npx skills` installation and usage |

---

### Task 1: Packaging Baseline and CLI Skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `.github/workflows/test.yml`
- Create: `wenlint/feishu/__init__.py`
- Create: `wenlint/feishu/cli.py`
- Create: `tests/feishu/test_packaging.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `wenlint.feishu.cli.main(argv: list[str] | None = None) -> int`
- Preserves: `wenlint.cli.main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Write packaging and compatibility tests**

```python
def test_pyproject_declares_supported_python_and_scripts():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["requires-python"] == ">=3.11"
    assert data["project"].get("dependencies") == []
    assert data["project"]["optional-dependencies"]["test"] == ["pytest>=8.4,<10"]
    assert data["project"]["scripts"]["wenlint"] == "wenlint.cli:main"
    assert data["project"]["scripts"]["wenlint-feishu"] == "wenlint.feishu.cli:main"


def test_local_cli_still_accepts_path_named_feishu(tmp_path, monkeypatch):
    target = tmp_path / "feishu"
    target.write_text("这是普通正文。", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["feishu"]) == 0
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run: `python -m pytest tests/feishu/test_packaging.py tests/test_cli.py -q --basetemp .pytest-plan-task1`

Expected: packaging test fails because Python floor, test extra, script, and new module are absent; existing local CLI test passes.

- [ ] **Step 3: Add packaging metadata, CI, and a safe CLI skeleton**

Set these exact project fields:

```toml
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
test = ["pytest>=8.4,<10"]

[project.scripts]
wenlint = "wenlint.cli:main"
wenlint-feishu = "wenlint.feishu.cli:main"
```

The initial Feishu parser exposes `inspect` and `apply` subcommands plus the URL shortcut. Until later tasks wire behavior, routes return exit 2 with a structured “not implemented” error; `--help` and `--version` return normally. Add Google Style module and function docstrings from the start.

Create GitHub Actions with this exact matrix:

```yaml
strategy:
  matrix:
    python-version: ["3.11", "3.13", "3.14"]
steps:
  - uses: actions/checkout@v4
  - uses: actions/setup-python@v5
    with:
      python-version: ${{ matrix.python-version }}
  - run: python -m pip install -e ".[test]"
  - run: python -m pytest -q
```

- [ ] **Step 4: Run packaging and legacy tests**

Run: `python -m pytest tests/feishu/test_packaging.py tests/test_cli.py -q --basetemp .pytest-plan-task1`

Expected: all selected tests pass.

- [ ] **Step 5: Commit the baseline**

```text
git add pyproject.toml .github/workflows/test.yml wenlint/feishu tests/feishu/test_packaging.py tests/test_cli.py
git commit -m "build: establish WenLint 0.2 Python baseline"
```

---

### Task 2: Document References and Immutable Models

**Files:**
- Create: `wenlint/feishu/models.py`
- Create: `wenlint/feishu/document.py`
- Create: `tests/feishu/test_document.py`
- Modify: `wenlint/feishu/__init__.py`

**Interfaces:**
- Produces: `parse_document_ref(raw: str) -> DocumentRef`
- Produces frozen models: `DocumentRef`, `SourceSpan`, `Section`, `DocumentSnapshot`, `BoundFinding`, `Patch`, `ApprovedSectionPlan`, `InspectionReport`
- `DocumentRef.kind` is `Literal["docx", "wiki"]`; parsing sets `input_token`, while fetch returns a new frozen reference with non-null actual Docx `document_id` and `canonical_url`.

- [ ] **Step 1: Write URL and model tests**

```python
@pytest.mark.parametrize(
    ("url", "kind", "token"),
    [
        ("https://acme.feishu.cn/docx/DocToken", "docx", "DocToken"),
        ("https://acme.feishu.cn/wiki/WikiToken", "wiki", "WikiToken"),
        ("https://acme.larksuite.com/docx/DocToken#share-AbC", "docx", "DocToken"),
    ],
)
def test_parse_supported_document_urls(url, kind, token):
    ref = parse_document_ref(url)
    assert (ref.kind, ref.input_token) == (kind, token)
    assert ref.input_url.partition("?")[0].startswith("https://")
    assert ref.document_id is None
    assert ref.canonical_url is None


@pytest.mark.parametrize(
    "raw",
    ["http://acme.feishu.cn/docx/x", "https://acme.feishu.cn/sheets/x", "docx-token"],
)
def test_reject_unsupported_or_ambiguous_input(raw):
    with pytest.raises(DocumentRefError):
        parse_document_ref(raw)
```

Also assert every model is frozen and `SourceSpan` permits `block_id=None` and `node_path=None` for synthetic spans.

- [ ] **Step 2: Run tests and confirm missing interfaces fail**

Run: `python -m pytest tests/feishu/test_document.py -q --basetemp .pytest-plan-task2`

Expected: import failure for the new models and parser.

- [ ] **Step 3: Implement exact parsing and models**

Use `urllib.parse.urlsplit`; accept only HTTPS hosts and exact `/docx/<token>` or `/wiki/<token>` path segments. Preserve a valid `#share-...` anchor for reading but remove query parameters from stored/loggable URLs. Reject credentials in URL userinfo, empty tokens, other products, and bare tokens. URL parsing leaves unresolved `document_id` and `canonical_url` as `None`; only a validated fetch response may populate them in a replacement frozen instance.

Every public model and parser has a Google Style docstring. `Patch` stores source offsets as well as node path so overlap can be rejected without re-searching strings.

- [ ] **Step 4: Run document tests**

Run: `python -m pytest tests/feishu/test_document.py -q --basetemp .pytest-plan-task2`

Expected: all tests pass.

- [ ] **Step 5: Commit document models**

```text
git add wenlint/feishu/models.py wenlint/feishu/document.py wenlint/feishu/__init__.py tests/feishu/test_document.py
git commit -m "feat: add Feishu document domain models"
```

---

### Task 3: Bounded `lark-cli` Adapter

**Files:**
- Create: `wenlint/feishu/lark.py`
- Create: `tests/feishu/test_lark.py`
- Create: `tests/feishu/fake_lark_cli.py`
- Create: `tests/feishu/fixtures/fetch_success.json`
- Create: `tests/feishu/fixtures/update_success.json`

**Interfaces:**
- Produces: `LarkClient(executable="lark-cli", fetch_timeout=60.0, update_timeout=30.0)`
- Produces: `LarkClient.probe() -> str`
- Produces: `LarkClient.fetch(ref: DocumentRef) -> Mapping[str, object]`
- Produces: `LarkClient.replace_block(ref: DocumentRef, block_id: str, xml: str, revision_id: int) -> Mapping[str, object]`
- Raises: `LarkCliError(kind: str, message: str, retryable: bool, details: Mapping[str, object])`

- [ ] **Step 1: Write argv, success, and failure contract tests**

```python
RESOLVED_REF = dataclasses.replace(
    parse_document_ref(DOC_URL),
    document_id="DocToken",
    canonical_url=DOC_URL,
)


def test_fetch_uses_full_xml_user_identity(fake_lark):
    client = LarkClient(executable=fake_lark.executable)
    response = client.fetch(parse_document_ref(DOC_URL))
    assert response["ok"] is True
    assert fake_lark.last_argv == [
        "docs", "+fetch", "--doc", DOC_URL,
        "--doc-format", "xml", "--detail", "full",
        "--as", "user", "--format", "json",
    ]


def test_update_requires_revision_and_block_replace(fake_lark):
    client = LarkClient(executable=fake_lark.executable)
    client.replace_block(RESOLVED_REF, "blk1", "<p>新文本</p>", 9)
    assert "str_replace" not in fake_lark.last_argv
    assert "overwrite" not in fake_lark.last_argv
    assert fake_lark.last_argv[fake_lark.last_argv.index("--revision-id") + 1] == "9"
```

Add cases for missing executable, timeout, nonzero exit, malformed JSON, exit 0 with `ok=false`, `partial_success`, missing revision, stdout over 20 MiB, stderr over 1 MiB, authentication, missing scope, permission, network, and hostile URL/XML characters remaining one argv element.

- [ ] **Step 2: Run adapter tests and confirm failure**

Run: `python -m pytest tests/feishu/test_lark.py -q --basetemp .pytest-plan-task3`

Expected: import failure for `LarkClient`.

- [ ] **Step 3: Implement bounded process collection**

Use `subprocess.Popen(..., shell=False, stdin=subprocess.DEVNULL, stdout=PIPE, stderr=PIPE)`. Read stdout and stderr concurrently with two threads into capped bytearrays. If either cap is exceeded, set a shared event, terminate the process, and raise `LarkCliError(kind="output_limit", retryable=False, ...)`. Kill after a short terminate grace period. Decode UTF-8 strictly after successful collection.

`probe()` runs `lark-cli --version`, `docs +fetch --help`, and `docs +update --help`; it requires the flags and commands listed in spec section 9.1. It returns the version text but gates on capabilities, not semantic version comparison.

- [ ] **Step 4: Implement JSON and error normalization**

Success requires process return code 0 and top-level `ok is True`. Update additionally requires `data.result == "success"`; warnings remain in the returned mapping for verification. Normalize only safe fields such as `missing_scopes`, `hint`, and error kind. Never include complete stdout, stderr, environment, XML, or URL query strings in the exception.

- [ ] **Step 5: Run adapter tests**

Run: `python -m pytest tests/feishu/test_lark.py -q --basetemp .pytest-plan-task3`

Expected: all tests pass.

- [ ] **Step 6: Commit the adapter**

```text
git add wenlint/feishu/lark.py tests/feishu/test_lark.py tests/feishu/fake_lark_cli.py tests/feishu/fixtures
git commit -m "feat: add bounded lark-cli adapter"
```

---

### Task 4: Safe XML Projection, SourceMap, and Sections

**Files:**
- Create: `wenlint/feishu/projection.py`
- Create: `wenlint/feishu/sections.py`
- Create: `tests/feishu/test_projection.py`
- Create: `tests/feishu/test_sections.py`
- Create: `tests/feishu/fixtures/structured_document.xml`
- Create: `tests/feishu/fixtures/duplicate_sections.xml`

**Interfaces:**
- Produces: `project_xml(xml: str, ref: DocumentRef, revision_id: int) -> DocumentSnapshot`
- Produces: `serialize_block(snapshot: DocumentSnapshot, block_id: str) -> str`
- Produces: `replace_node_text(snapshot: DocumentSnapshot, patch: Patch) -> str`
- Produces: `section_fingerprint(element: Element) -> str`
- Produces: `locate_section(snapshot: DocumentSnapshot, locator: str) -> Section`

- [ ] **Step 1: Write XML security and projection tests**

```python
def test_projection_preserves_scanner_roles():
    snapshot = project_xml(FIXTURE_XML, REF, revision_id=7)
    lines = snapshot.projection.splitlines()
    assert "# 一级标题" in lines
    assert "普通正文可能含糊。" in lines
    assert "- 列表正文" in lines
    assert "> 引用正文" in lines
    assert "https://internal.example" not in snapshot.projection


@pytest.mark.parametrize("payload", ["<!DOCTYPE x>", "<!ENTITY x SYSTEM 'file:///x'>"])
def test_rejects_dtd_and_entities(payload):
    with pytest.raises(XmlSafetyError):
        project_xml(payload, REF, revision_id=1)
```

Assert that heading/list/blockquote prefixes and separator newlines have `writable=False`; visible text characters point to the correct block ID, node path, and source offset. Assert input larger than 20 MiB and malformed XML fail.

- [ ] **Step 2: Write section and fingerprint tests**

```python
def test_section_fingerprint_ignores_block_ids_not_text():
    first = project_xml(XML_WITH_BLOCK_ID_A, REF, 1).sections[0]
    renamed_ids = project_xml(XML_WITH_BLOCK_ID_B, REF, 2).sections[0]
    changed_text = project_xml(XML_WITH_CHANGED_TEXT, REF, 3).sections[0]
    assert first.fingerprint == renamed_ids.fingerprint
    assert first.fingerprint != changed_text.fingerprint
```

Cover nested headings, same-name sibling ordinals, content before the first heading, no headings, structure/attribute/resource changes, and ambiguous duplicate locators.

- [ ] **Step 3: Run projection tests and confirm failure**

Run: `python -m pytest tests/feishu/test_projection.py tests/feishu/test_sections.py -q --basetemp .pytest-plan-task4`

Expected: imports fail because projection and section functions are absent.

- [ ] **Step 4: Implement secure parse and deterministic projection**

Reject DTD/ENTITY markers before wrapping the block sequence in a synthetic `<document>` root and parsing with `ElementTree`. Do not resolve URLs or external data. Preserve a private element tree inside the snapshot implementation without exposing mutable elements through public models.

Project `h1`-`h9`, `p`, `li`, `blockquote`, `checkbox`, supported inline tags, and callout text as specified. Exclude code, tables, grids, resources, and reference sidecars from writable mappings. Use exact XML text, not Unicode or whitespace normalization, for source offsets.

- [ ] **Step 5: Implement sections and canonical fingerprints**

Build locators from heading title paths plus one-based same-name sibling ordinals. Canonical XML excludes volatile ID/revision attributes, sorts attributes, preserves tag order, text, tails, semantic attributes, and resource references, then hashes UTF-8 bytes with SHA-256.

- [ ] **Step 6: Run projection and section tests**

Run: `python -m pytest tests/feishu/test_projection.py tests/feishu/test_sections.py -q --basetemp .pytest-plan-task4`

Expected: all tests pass.

- [ ] **Step 7: Commit projection and sections**

```text
git add wenlint/feishu/projection.py wenlint/feishu/sections.py tests/feishu/test_projection.py tests/feishu/test_sections.py tests/feishu/fixtures
git commit -m "feat: map Feishu XML to stable source spans"
```

---

### Task 5: Finding Binding and Read-Only Inspection

**Files:**
- Create: `wenlint/feishu/findings.py`
- Create: `wenlint/feishu/inspection.py`
- Create: `tests/feishu/test_findings.py`
- Create: `tests/feishu/test_inspection.py`
- Modify: `wenlint/feishu/cli.py`

**Interfaces:**
- Produces: `bind_findings(snapshot: DocumentSnapshot, findings: Sequence[Mapping[str, object]]) -> tuple[BoundFinding, ...]`
- Produces: `inspect_document(client: LarkClient, ref: DocumentRef, profile: str = "general") -> InspectionReport`
- Produces: `InspectionReport.to_dict() -> dict[str, object]`

- [ ] **Step 1: Write binding tests**

```python
def test_binds_exact_single_node_finding():
    snapshot = project_xml(SIMPLE_XML, REF, 4)
    findings = scan_text(snapshot.projection)
    bound = bind_findings(snapshot, findings)
    target = next(item for item in bound if item.rule == "H002")
    assert target.location.mapping_status == "exact"
    assert target.location.block_id == "blkParagraph"
    assert target.location.writable is True


def test_cross_inline_node_is_report_only():
    bound = bind_findings(project_xml(CROSS_NODE_XML, REF, 4), CROSS_NODE_FINDINGS)
    assert bound[0].location.writable is False
    assert bound[0].location.reason == "cross_node"
```

Cover synthetic spans, unsupported blocks, duplicate source, missing match, S001 empty match, and unmapped coordinates.

- [ ] **Step 2: Write inspection tests with a fake client**

```python
def test_inspect_fetches_once_and_never_updates(fake_client):
    report = inspect_document(fake_client, REF, profile="formal")
    assert fake_client.fetch_calls == 1
    assert fake_client.replace_calls == []
    assert report.source.identity == "user"
    assert report.source.revision_id == 12
```

Assert Wiki input uses returned `document_id` and canonical Docx URL, malformed fetch schemas fail without partial findings, and JSON contains source, sections, findings, location, block URL, and mapping reason.

- [ ] **Step 3: Run binding and inspection tests and confirm failure**

Run: `python -m pytest tests/feishu/test_findings.py tests/feishu/test_inspection.py -q --basetemp .pytest-plan-task5`

Expected: missing binding and inspection interfaces.

- [ ] **Step 4: Implement exact coordinate binding**

Convert one-based scanner line/column to a projection offset using precomputed line starts. For non-empty matches, require the entire range to map to contiguous source spans in one writable block and one node, and require exact XML text equality. Set stable reasons instead of searching for another occurrence.

- [ ] **Step 5: Implement inspection orchestration and CLI output**

Fetch once, validate `data.document.revision_id` and XML content, resolve canonical document metadata, project, call existing `scan_text`, bind, and serialize. The URL shortcut and `inspect` route call only this service. JSON success goes to stdout; compact errors without document content go to stderr with exit codes from the spec.

- [ ] **Step 6: Run selected and full legacy tests**

Run: `python -m pytest tests/feishu/test_findings.py tests/feishu/test_inspection.py tests/test_engine.py tests/test_cli.py -q --basetemp .pytest-plan-task5`

Expected: all tests pass and no existing local JSON fixture changes.

- [ ] **Step 7: Commit read-only inspection**

```text
git add wenlint/feishu/findings.py wenlint/feishu/inspection.py wenlint/feishu/cli.py tests/feishu/test_findings.py tests/feishu/test_inspection.py
git commit -m "feat: inspect Feishu documents without writes"
```

---

### Task 6: Approved Patch Manifest and Safe Writeback

**Files:**
- Create: `wenlint/feishu/patches.py`
- Create: `tests/feishu/test_patches.py`
- Create: `tests/feishu/test_writeback.py`
- Modify: `wenlint/feishu/cli.py`
- Modify: `wenlint/feishu/models.py`

**Interfaces:**
- Produces: `load_manifest(path: Path, expected_ref: DocumentRef) -> ApprovedSectionPlan`
- Produces: `validate_patches(snapshot: DocumentSnapshot, plan: ApprovedSectionPlan) -> tuple[Patch, ...]`
- Produces: `apply_approved_section(client: LarkClient, ref: DocumentRef, plan: ApprovedSectionPlan) -> ApplyResult`
- `ApplyResult.status` is `"success"`, `"conflict"`, or `"partial_failure"` and always lists applied, unapplied, and reconfirm patch IDs.

- [ ] **Step 1: Write manifest validation tests**

```python
def test_manifest_must_match_document_and_section(tmp_path):
    path = write_manifest(tmp_path, document_id="another-doc")
    with pytest.raises(ManifestError) as exc:
        load_manifest(path, REF)
    assert exc.value.kind == "document_mismatch"


def test_overlapping_patches_are_rejected(snapshot):
    plan = approved_plan(patches=[patch(2, 5), patch(4, 7)])
    with pytest.raises(PatchValidationError) as exc:
        validate_patches(snapshot, plan)
    assert exc.value.kind == "overlapping_patches"
```

Cover files outside the current working directory, files over 1 MiB, malformed JSON, unknown fields, duplicate IDs, unapproved IDs, empty/equal before-after, cross-node patches, source mismatch, invalid XML after replacement, and changes to attributes/resources/unapproved nodes.

- [ ] **Step 2: Write writeback state-machine tests**

```python
def test_refetches_after_every_block_and_uses_new_revision(scripted_client):
    result = apply_approved_section(scripted_client, REF, TWO_BLOCK_PLAN)
    assert result.status == "success"
    assert scripted_client.events == [
        "fetch:r10", "replace:blkA:r10", "fetch:r11",
        "replace:blkB-new:r11", "fetch:r12", "final-inspect:r12",
    ]


def test_other_section_change_can_retry_revision_conflict(scripted_client):
    scripted_client.conflict_once_with_unchanged_target_section()
    result = apply_approved_section(scripted_client, REF, PLAN)
    assert result.status == "success"
    assert scripted_client.replace_attempts == 2
```

Also cover target-section change requiring reconfirmation, two consecutive revision conflicts, block/original-text mismatch, warning plus successful verification, warning plus failed verification, partial failure after one write, zero automatic rollback, stale block IDs never reused, and final full-document rescan.

- [ ] **Step 3: Run patch tests and confirm failure**

Run: `python -m pytest tests/feishu/test_patches.py tests/feishu/test_writeback.py -q --basetemp .pytest-plan-task6`

Expected: missing manifest and writeback interfaces.

- [ ] **Step 4: Implement strict manifest loading and patch grouping**

Resolve both the manifest and current working directory; reject paths outside the latter. Parse UTF-8 JSON with a 1 MiB cap and exact allowed fields. Validate initial section fingerprint before edits. Group non-overlapping patches by block and apply node replacements from highest source offset to lowest so earlier offsets remain stable.

Before serialization, deep-copy the block. Compare the original and patched trees and permit changes only to approved text node contents. Tag names, attributes, child order, tails outside approved ranges, and resource references must remain identical.

- [ ] **Step 5: Implement writeback and bounded conflict retry**

Fetch before the section, map using locator plus expected fingerprint, and compute expected fingerprint after each grouped block patch. Update with the latest explicit revision. On revision conflict only, fetch again; if the target section still equals the pre-write expected fingerprint, remap and retry once. Any target change, second conflict, verification mismatch, or other error stops later writes.

After each successful update, fetch again, verify text/tree/expected fingerprint, and remap remaining patches. At the end call read-only inspection on the latest document. Never call an inverse update for rollback.

- [ ] **Step 6: Wire `apply` CLI status and exit codes**

Return 0 for verified success, 2 for invalid manifest, 3 for dependency/auth/network/protocol failures, 4 for a conflict before any new write, and 5 for failure after at least one write. Output patch IDs and revisions but never the complete before/after text or block XML.

- [ ] **Step 7: Run patch, CLI, and full tests**

Run: `python -m pytest -q --basetemp .pytest-plan-task6`

Expected: all tests pass.

- [ ] **Step 8: Commit safe writeback**

```text
git add wenlint/feishu/patches.py wenlint/feishu/cli.py wenlint/feishu/models.py tests/feishu/test_patches.py tests/feishu/test_writeback.py
git commit -m "feat: apply approved Feishu patches safely"
```

---

### Task 7: Codex Skill Chapter Checkpoints

**Files:**
- Modify: `SKILL.md`
- Create: `references/feishu.md`
- Create: `tests/test_skill_contract.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `wenlint-feishu <url> --json` and `wenlint-feishu apply <url> --patch-file <path> --json`
- Produces: one public Skill named `wenlint`, with Feishu details loaded only for Docx/Wiki input.

- [ ] **Step 1: Write static Skill contract tests**

```python
def test_feishu_skill_requires_chapter_approval():
    root = Path("SKILL.md").read_text(encoding="utf-8")
    ref = Path("references/feishu.md").read_text(encoding="utf-8")
    assert "references/feishu.md" in root
    assert "wenlint-feishu" in root
    for phrase in ["先展示总览", "逐章", "排除", "跳过", "停止", "未明确批准"]:
        assert phrase in ref


def test_read_only_and_write_safety_rules_are_documented():
    text = Path("references/feishu.md").read_text(encoding="utf-8")
    for phrase in ["KEEP", "REWRITE", "VERIFY", "ASK", "--as user", "block_replace"]:
        assert phrase in text
    for forbidden in ["str_replace", "overwrite", "模糊匹配", "强制写入"]:
        assert f"禁止 `{forbidden}`" in text or f"禁止{forbidden}" in text
```

Add tests that inspect/give-diff intents forbid update; only REWRITE and evidenced VERIFY enter the manifest; conflict invalidates chapter approval; every block write requires fetch/remap; prompt injection text is data; the root frontmatter remains `name: wenlint`.

- [ ] **Step 2: Run Skill tests and confirm failure**

Run: `python -m pytest tests/test_skill_contract.py -q --basetemp .pytest-plan-task7`

Expected: failure because `references/feishu.md` and routing text do not exist.

- [ ] **Step 3: Update the root Skill without duplicating lark manuals**

Keep the root file concise. Route local paths to existing `wenlint`; route `/docx/` and `/wiki/` URLs to `references/feishu.md`; treat a bare token as Feishu only when the user explicitly identifies it. Preserve four-class semantics and the “only edit findings unless broader editing is explicitly requested” rule.

The Feishu reference defines this exact interaction order:

```text
inspect → four-class review → overall summary
→ present one section → approve all / exclude IDs / skip / stop
→ create temp manifest for approved IDs → apply → verify
→ ask about next section → final full inspection summary
```

State that no response, unclear approval, KEEP, ASK, or unsupported mapping means no write. State that changed target sections are rescanned and reconfirmed. Include dependency recovery without silently installing packages or requesting broader scopes.

- [ ] **Step 4: Update README installation and examples**

Document `pipx install wenlint`, venv development install, `npx skills add DreamStars1/WenLint --skill wenlint --agent codex --global`, the fact that npx does not install Python or lark-cli, Docx/Wiki support, inspect/apply boundaries, and Python support policy.

- [ ] **Step 5: Run Skill and WenLint checks**

Run: `python -m pytest tests/test_skill_contract.py -q --basetemp .pytest-plan-task7`

Run: `python -m wenlint SKILL.md references/feishu.md README.md --profile instruction --json`

Expected: tests pass. Review every WenLint finding; fix genuine instruction ambiguity and record semantically valid KEEP cases in the task output rather than weakening rules.

- [ ] **Step 6: Commit Skill and documentation**

```text
git add SKILL.md references/feishu.md README.md tests/test_skill_contract.py
git commit -m "docs: add Feishu chapter approval workflow"
```

---

### Task 8: Distribution, Documentation, and Final Regression

**Files:**
- Modify: `README.md`
- Modify: files found deficient by the Google Style docstring review
- Create: `tests/feishu/test_cli_contract.py`

**Interfaces:**
- Verifies the complete public contract; produces no new runtime API unless a failing acceptance test exposes a missing seam.

- [ ] **Step 1: Add end-to-end fake CLI tests**

Run the installed console entry via `subprocess.run([sys.executable, "-m", "wenlint.feishu.cli", ...], shell=False)` with the fake `lark-cli` first on PATH. Verify inspect success, Wiki resolution, missing auth, conflict, successful two-block apply, partial failure, stdout/stderr privacy, and exact exit codes 0/2/3/4/5.

- [ ] **Step 2: Run the new end-to-end tests**

Run: `python -m pytest tests/feishu/test_cli_contract.py -q --basetemp .pytest-plan-task8`

Expected: all scenarios pass after fixing only contract gaps revealed by the tests.

- [ ] **Step 3: Review Google Style docstrings manually**

Inspect every module, class, function, and method in `wenlint/feishu/` plus substantially modified existing Python files. Confirm summaries are imperative, actual parameters match `Args:`, return paths match `Returns:`, raised public exceptions match `Raises:`, non-obvious dataclass fields use `Attributes:`, and comments explain safety/protocol reasons rather than restating statements. Correct every mismatch before continuing.

- [ ] **Step 4: Run the full Python matrix available locally**

Run with Python 3.11, 3.13, and 3.14 when installed:

```text
<python> -m pip install -e ".[test]"
<python> -m pytest -q --basetemp <workspace-temp-for-version>
```

The mandatory local acceptance runtime is Python 3.13. Missing secondary interpreters are not reported as passing; CI is the evidence for unavailable matrix entries.

- [ ] **Step 5: Build and smoke-test distributions**

```text
python -m pip wheel . --no-deps --wheel-dir dist-test
python -m venv .venv-dist-test
.venv-dist-test/Scripts/python -m pip install --no-deps dist-test/wenlint-*.whl
.venv-dist-test/Scripts/wenlint --version
.venv-dist-test/Scripts/wenlint-feishu --help
```

Use platform-equivalent `bin/` paths outside Windows. Remove only these task-created acceptance directories after recording results.

- [ ] **Step 6: Verify Skill discovery without installing globally**

Run: `npx skills add . --list`

Expected: one discoverable Skill named `wenlint`. Do not use `--global` during repository acceptance.

- [ ] **Step 7: Run final safety and repository checks**

```text
python -m pytest -q --basetemp .pytest-final
python -m wenlint SKILL.md references/feishu.md README.md --profile instruction --json
git diff --check
git status --short
```

Search for prohibited update paths and placeholders:

```text
rg -n "str_replace|overwrite|shell=True|revision_id\s*=\s*-1|(T)(BD)|(T)(ODO)|(F)(IXME)" wenlint tests SKILL.md references README.md
```

Every search hit must be an explicit prohibition/test assertion or be removed. Full pytest must pass; no generated build, venv, pytest temp, credential, XML body, or patch manifest may remain untracked.

- [ ] **Step 8: Commit final acceptance fixes**

```text
git add pyproject.toml .github wenlint tests SKILL.md references README.md
git commit -m "test: complete WenLint Feishu acceptance coverage"
```

If Step 8 has no changes because earlier tasks already satisfy acceptance, do not create an empty commit.
