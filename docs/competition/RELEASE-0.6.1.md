# WenLint 0.6.1

修复真实桌面审查发现的候选关联错位。模型将平台问题关联到发布日期候选时，后端现在依据扫描器的行列和原文校验，阻止错误合并；不能确认关联的语义建议独立保留。模型请求中的候选也显式编号。

包含0.6.0的GitHub风格diff、逐条确认、长文分段续查和实时工具过程。

## 下载

- Windows：完整解压 `WenLint-windows-x64.zip`，打开 `WenLint/WenLint.exe`，需要系统WebView2。
- Apple芯片Mac：解压 `WenLint-macos-arm64.zip`，打开 `WenLint.app`。
- Intel Mac：解压 `WenLint-macos-x64.zip`，打开 `WenLint.app`。

无需另装Python或Node。各包附校验和与构建清单；未提供发布者签名或Apple公证，Mac图形界面尚未人工验收。

## 实测边界

0.6.0最终包267字真实审查28.0秒、5次模型请求（含一次格式修复），实际读取两份参考资料；逐条确认、diff和原生导出已验证，导出逐字节只包含采纳项且保留LF。0.6.1的关联修复通过离线回归，未增加在线模型调用。部分模型引用行号仍有偏差，长文真实耗时尚未测量。完整证据见仓库 `docs/competition/FINAL_DESKTOP_REVIEW.md`。
