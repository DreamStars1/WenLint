# WenLint 0.6.0

中文文档检查、资料查证与逐条确认修改的桌面应用。

## 下载与启动

- Windows：下载 `WenLint-windows-x64.zip`，完整解压后打开 `WenLint/WenLint.exe`。需要系统 WebView2。
- Apple 芯片 Mac：下载 `WenLint-macos-arm64.zip`，解压后打开 `WenLint.app`。
- Intel Mac：下载 `WenLint-macos-x64.zip`，解压后打开 `WenLint.app`。

无需另装 Python 或 Node。各包附带 SHA-256 和构建清单。当前没有发布者签名或 Apple 公证，macOS 15 为构建验证基线；Mac 图形界面尚未人工验收。

## 本版变化

- GitHub 风格差异：原/新行号、增删行与字词高亮，逐条采纳、保留或撤销；只有采纳项进入输出。
- 长文按段审查，显示覆盖进度，每批最多两段；手动继续时保留已有决定。
- Agent 实时展示阶段、工具参数、结果和决策摘要，支持取消；模型请求的连续进度合并显示。
- 参考资料按页读取与搜索，限制单次内容和总预算；长单行支持字符续页。
- Windows 采用目录包，降低启动时反复解包的开销。

点击“体验示例”可先完成无密钥的离线流程。在线审查需配置自己的兼容模型服务，密钥只在当前进程内存中保存。

## 验证范围

发行代码对应提交 `28d6fc4a24df59d8f2ce74abecc4bf5989df08f2`，包含341项 Python 回归和30项前端测试。完整原生 Windows 在线体验曾用23.5秒完成267字审查并验证导出，但发现漏查参考资料；后续检索约束已有离线回归，追加在线复测尚未执行。长文的真实模型耗时也尚未测量。

详细记录保留在仓库的 `docs/competition/VALIDATION.md` 与 `FIRST_USER_REVIEW.md`，不把模拟结果当作模型性能或准确率保证。
