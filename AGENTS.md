# Local WenLint environment

- Do not rerun `lark-cli config init` or `lark-cli auth login` merely because
  `lark-cli` is absent from the Codex process `PATH`. The interactive PowerShell
  environment may use NVM while Codex uses its bundled Node runtime.
- For Feishu inspection in this workspace, use
  `scripts/wenlint-feishu-local.ps1`. It discovers `lark-cli` from the current
  process, `NVM_SYMLINK`, or the user-level `NVM_SYMLINK`, sets
  `WENLINT_LARK_CLI` only for the child process, and invokes the repository's
  `python -m wenlint.feishu.cli` module.
- Example (read-only):
  `./scripts/wenlint-feishu-local.ps1 inspect '<docx-or-wiki-url>' --json`
- If authentication genuinely fails, run a read-only
  `lark-cli auth status --json --verify` through the discovered executable and
  report the exact state before suggesting configuration changes.
- `inspect` is read-only. Never use `apply` unless the user explicitly asks for
  a write-back and the chapter-by-chapter approval workflow in
  `references/feishu.md` has been followed.
