# Wenlint Lark CLI Compatibility And Source Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Wenlint 0.2.x compatible with legacy and modern `lark-cli` dialects, normalize fetch/update behind `LarkClient`, support `id`/`block-id`/`block_id`, emit exact S001 spans, preserve Feishu hard block boundaries, and keep post-write fetch authoritative.

**Architecture:** Deepen `LarkClient` as the only seam that understands CLI argv dialects and JSON schemas; return `FetchedDocument` / `UpdateReceipt`. Centralize XML block-id dialect in `xml_protocol.block_id_of`. Keep scanner Markdown soft-wrap behavior; only Feishu projection inserts blank-line separators between top-level blocks.

**Tech Stack:** Python 3.11+, pytest, stdlib only runtime deps, offline fake `lark-cli`.

## Global Constraints

- Work only in `D:\wenlint\WenLint`; preserve untracked review/spec docs; no commit/push/PR/reset/stash/clean/`--force`.
- No real Feishu/network access; no real review URL/document/block/body in fixtures.
- Preserve timeout, output-limit, env sanitization, privacy, fail-closed writeback.
- Verification: `PYTHONPATH=D:\wenlint\WenLint` and unique workspace-local `--basetemp`.

---

### Task 1: Domain models + modern fixtures + dialect fake

**Files:**
- Modify: `wenlint/feishu/models.py`
- Create: `tests/feishu/fixtures/fetch_success_modern.json`
- Modify: `tests/feishu/fake_lark_cli.py`
- Create/Modify: `tests/feishu/test_lark.py`, `tests/feishu/test_xml_protocol.py`

- [ ] Add frozen `FetchedDocument` / `UpdateReceipt`
- [ ] Extend fake CLI with `FAKE_LARK_DIALECT=legacy|modern`
- [ ] Tests for modern/legacy argv and content paths

### Task 2: Deepen LarkClient normalization

**Files:**
- Modify: `wenlint/feishu/lark.py`
- Modify: `tests/feishu/test_lark.py`

- [ ] `_CliCapabilities` cache, optional `--format json`
- [ ] `fetch()` → `FetchedDocument`; `replace_block()` → `UpdateReceipt`
- [ ] Missing executable NVM hint

### Task 3: Migrate callers off raw mapping

**Files:**
- Modify: `wenlint/feishu/inspection.py`, `patches.py`, `cli.py`
- Modify: related tests / in-process fakes in `tests/feishu/test_writeback.py`

### Task 4: XML protocol + projection/sections

**Files:**
- Create: `wenlint/feishu/xml_protocol.py`
- Modify: `projection.py`, `sections.py`
- Update fingerprint tests for volatile `id`

### Task 5: S001 exact match + hard Feishu boundaries

**Files:**
- Modify: `wenlint/scanner.py`, `wenlint/feishu/projection.py`
- Modify/Create: engine and Feishu binding tests

### Task 6: Docs + full verification

**Files:**
- Modify: `README.md`, `references/feishu.md`, `docs/superpowers/specs/2026-09-06-wenlint-feishu-codex-skill-design.md`
- Run focused tests, full pytest, package build checks
