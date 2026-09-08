# Windows 与 macOS 桌面分发

## 获取应用

在 GitHub 仓库 Actions 中手动运行 **build-desktop**（文件名保留为 `build-windows.yml`），完成后下载对应 artifact。推送 `v*` 标签时，所有平台测试和构建成功后统一发布到 GitHub Release。源代码推送本身不会生成发行标签。

| 平台 | 构建环境 | 文件 | 启动方式 |
|---|---|---|---|
| Windows x64 | `windows-latest` + Python 3.13 x64 | `WenLint-windows-x64.zip` | 完整解压，双击 `WenLint/WenLint.exe` |
| Apple silicon Mac | `macos-15` + Python 3.13 arm64 | `WenLint-macos-arm64.zip` | 解压后打开 `WenLint.app` |
| Intel Mac | `macos-15-intel` + Python 3.13 x64 | `WenLint-macos-x64.zip` | 解压后打开 `WenLint.app` |

macOS 15 是当前 CI 验证基线，较旧系统尚未验证。Windows 使用系统 WebView2 环境；没有 WebView2 的机器需先安装微软运行时。飞书 CLI 不是桌面包内置组件。应用内不含 API Key，在线语义审查由使用者配置模型服务。

Windows 采用目录分发，减少单文件程序启动时重复解包的成本；请保留 `_internal` 等全部文件。macOS 使用 `.app` bundle。CI 通过 `ditto` 保留 Mac bundle 的资源与权限。三个包各自包含 `.sha256` 和 `.build.json`，后者记录提交、Python、平台及构建环境安装的 Python 包版本（包括构建工具，不等同于精确运行时 SBOM）。

**当前构建未使用发布者代码签名，macOS 未经 Apple 公证**，首次打开可能被系统阻止。请先核对来源和校验值，再按系统提供的批准方式处理；组织设备应遵守其管理员策略。这不影响从源码运行，但签名/公证是正式面向广泛用户发布时仍需完成的工作。macOS 包必须由 Mac runner 实际构建成功后才可宣称可下载；Windows 开发机不能验证原生 Mac 窗口。

## 本地构建

需要 Python 3.13、Node.js 22 和 pnpm 10.15.1。先在虚拟环境安装 `python -m pip install -e ".[test,desktop-build]"`。

Windows PowerShell：

```powershell
./scripts/build-windows.ps1 -Python python
# 输出：dist/WenLint/WenLint.exe
```

目标架构的 macOS：

```bash
bash scripts/build-macos.sh
# 输出：dist/WenLint.app
```

已有本次代码对应的前端生产资源时，Windows 可传 `-SkipFrontend`，Mac 可传 `--skip-frontend`。两者都不会自动安装 Python 构建依赖。`--self-test` 检查内置前端资源和 pywebview 导入，并不替代图形界面人工验收。

构建选择依据：[GitHub 官方 runner 架构表](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)、[PyInstaller 官方用法](https://pyinstaller.org/en/stable/usage.html#building-macos-app-bundles)。
