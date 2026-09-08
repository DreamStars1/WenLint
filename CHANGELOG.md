# Changelog

本项目遵循语义化版本；日期使用 YYYY-MM-DD。

## [0.3.0] - 2026-09-08

### Added

- Vue 3 + pywebview 桌面工作台和 Windows 单文件 EXE 构建流程。
- OpenAI-compatible 内置 Agent、KEEP / REWRITE / VERIFY / ASK 输出契约。
- 发送前确认、内存密钥、修改稿预览与显式另存为安全边界。
- Windows 构建 artifact 与打包后 smoke test。

### Changed

- Windows CI 使用仓库内 pytest 临时目录和 UTF-8 环境，避免系统临时目录权限与编码差异。

## [0.2.0] - 2026-09-08

- 增加讨论/纠偏过程痕迹及上下文依赖措辞检查。
- 扩展 Markdown、飞书文档覆盖和反馈记录能力。
