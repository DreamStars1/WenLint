# WenLint 桌面界面参考研究

> 研究范围：仅使用项目自身的 GitHub 仓库、官方文档、截图与源码。目标不是复制视觉资产，而是提炼可复用的信息架构、交互和样式原则。

## 结论

建议采用“**克制的编辑审查台**”方向：以浅色、中性、接近原生桌面工具的界面为默认；正文始终占据最大视觉面积；检查结果使用紧凑列表和选中项详情；模型连接移入设置抽屉；修改稿改为真正的统一/并排差异视图。整体取 **Zettlr/Joplin 的写作专注感 + VS Code 的 Problems 模型 + GitHub Desktop 的 diff 纪律 + Zed 的可调密度**。

## 5 个强参考

### 1. Visual Studio Code：诊断是编辑器的辅助层

- [源码仓库](https://github.com/microsoft/vscode)、[工作台区域说明](https://github.com/microsoft/vscode-docs/blob/main/docs/editing/getting-started/userinterface.md)、[错误与警告交互](https://github.com/microsoft/vscode-docs/blob/main/docs/editing/editingevolved.md)、[可移动 Panel](https://github.com/microsoft/vscode-docs/blob/main/docs/configure/custom-layout.md)、[诊断颜色令牌](https://github.com/microsoft/vscode-docs/blob/main/api/references/theme-color.md)
- 可复用原则：正文是中心工作区；问题同时存在于正文标记、状态汇总和 Problems 列表中；点击问题可定位原文；辅助 Panel 可收起、移动，不长期挤占内容；错误、警告、信息使用稳定的语义色令牌，而不是每张卡片重新装饰。
- 用于 WenLint：右侧结果区改成紧凑问题列表；每项显示严重度、规则、摘要和行号，点击后定位正文并显示详情。底部状态栏只保留“问题数 / 待核实数 / 字符数”。

### 2. GitHub Desktop：列表负责选择，主区负责比较

- [源码仓库与官方截图](https://github.com/desktop/desktop)、[审阅修改说明](https://docs.github.com/en/desktop/making-changes-in-a-branch/committing-and-reviewing-changes-to-your-project-in-github-desktop)、[Diff 组件源码](https://github.com/desktop/desktop/blob/development/app/src/ui/diff/index.tsx)
- 可复用原则：左侧列表建立审阅范围，右侧只展示当前选中对象；统一 diff 与并排 diff 可以切换；默认聚焦真实变化，并允许按需展开上下文；动作紧邻其作用对象。
- 用于 WenLint：不要把每条裁决都做成独立“双栏小卡片”。选中一条问题后，在详情区展示原因、原文、建议及“接受/忽略/待核实”；全文修改稿进入独立 diff 模式，支持统一/并排切换。

### 3. Joplin：内容优先、离线优先、布局可切换

- [源码仓库](https://github.com/laurent22/joplin)、[Markdown/离线能力说明](https://github.com/laurent22/joplin#readme)、[编辑器/预览/分栏布局常量](https://github.com/laurent22/joplin/blob/dev/packages/lib/models/Setting.ts)、[集中式暗色主题](https://github.com/laurent22/joplin/blob/dev/packages/lib/themes/dark.ts)、[GUI 样式约定](https://github.com/laurent22/joplin/blob/dev/readme/dev/index.md#gui-style)
- 可复用原则：编辑、预览和分栏是同一内容的不同工作模式；界面颜色来自集中主题令牌；隐私是产品行为而非持续发光的装饰；工具栏和侧栏服务于文档，不与文档竞争视觉焦点。
- 用于 WenLint：将“原文 / 修改 diff / 修改稿”设计为编辑区模式，而不是结果面板的三个异质页面；本地检查与联网语义复核在按钮文字和确认流程上区分即可，不需要常驻隐私胶囊。

### 4. Zettlr：写作工具的排版应与应用外壳分层

- [源码仓库与功能说明](https://github.com/Zettlr/Zettlr)、[编辑器主题变量源码](https://github.com/Zettlr/Zettlr/blob/develop/source/common/modules/markdown-editor/theme/editor.ts)
- 可复用原则：编辑器有独立的字体、字号、行高、选区、引用、代码、标题和滚动条变量；内容排版与窗口 chrome 分开控制；大面积纯色背景和有限强调色比渐变卡片更适合长时间写作。
- 用于 WenLint：正文采用 15–16px 中文正文、约 1.65 行高、76–88ch 舒适行宽；UI 使用 12–14px 系统字体；不要让正文沿用代码编辑器式的全等宽字体。

### 5. Zed：高密度不等于字号小，密度应系统化

- [源码仓库](https://github.com/zed-industries/zed)、[外观与字体设置](https://github.com/zed-industries/zed/blob/main/docs/src/appearance.md)、[面板停靠与视觉定制](https://github.com/zed-industries/zed/blob/main/docs/src/visual-customization.md)、[UI density 源码](https://github.com/zed-industries/zed/blob/main/crates/settings_content/src/theme.rs)、[诊断工具说明](https://github.com/zed-industries/zed/blob/main/docs/src/ai/tools.md#diagnostics)
- 可复用原则：编辑字体与 UI 字体分离；compact/default/comfortable 通过统一间距比例实现，而不是把辅助文字压到 9px；面板可以停靠和隐藏；诊断先给项目级计数，再按文件/位置展开。
- 用于 WenLint：以 12px 作为元信息下限；通过 4/8/12/16px 间距阶梯获得密度；右侧审查栏支持收起，后续可增加“紧凑/舒适”密度设置。

## 当前界面的反模式

1. **模型配置抢占首屏。** `desktop-ui/src/App.vue:247-260` 将 Base URL、API Key、模型和场景放在正文上方，用户每次审稿都要先看一块基础设施表单。配置应进入齿轮按钮打开的抽屉；工具栏只显示当前服务的简短状态。
2. **静态步骤条制造伪流程。** `App.vue:237-245` 的 01–04 永远只高亮第一步，但审稿实际是“编辑—检查—修订—复查”的循环。删除步骤条，用当前模式、问题计数和按钮状态表达进度。
3. **以 Agent 为视觉主角。** `App.vue:279,298,319` 反复突出“Agent/AI”，空状态还使用 AI 字形。改为任务语言：“语义复核”“审查建议”“生成修改稿”；模型身份只在设置和请求确认中出现。
4. **装饰层过多。** `styles.css:23-24,44-46,68-73,126,131,140,159,172-173` 同时使用径向渐变、面板渐变、发光点、阴影、大圆角和卡片套卡片，形成典型生成式 AI 控制台观感。应使用纯色面、1px 分隔线、4–6px 圆角；阴影仅用于弹窗或浮层。
5. **“高密度”由微小字号实现。** `styles.css:76-83,102,112,120,132,139,141-143,152,156` 大量使用 9–10px，降低中文可读性。密度应来自更短文案、行式列表和稳定间距，而不是缩小文字。
6. **检查结果被卡片化，扫描效率低。** `App.vue:288-307` 与 `styles.css:131-152` 为每项重复边框、标签、引用框和 mini-diff。改为可筛选的行式列表；选中项再展示完整说明与差异。
7. **“完整修改稿”不是审阅视图。** `App.vue:311-314` 只是第二个可编辑 textarea，无法辨别 Agent 改了什么。改为 diff，默认仅显示变化和少量上下文，并提供“查看全文”。
8. **窄窗口直接隐藏关键配置。** `styles.css:181-184` 在 1050px 下隐藏场景字段。应让设置抽屉滚动或分组，不能静默丢失能力。

## 推荐视觉方向：克制的编辑审查台

### 信息架构

```text
┌ 文件名 / 打开 / 保存 ───────────── 场景  本地检查  语义复核  设置 ┐
├──────────────────────────────────────┬───────────────────────────┤
│                                      │ 问题 12  待核实 3   筛选  │
│              文档编辑区              ├───────────────────────────┤
│       行内标记；舒适行宽与行高         │ 紧凑问题列表               │
│                                      │ 选中项：说明 / 建议 / 操作   │
├──────────────────────────────────────┴───────────────────────────┤
│ 本地 · 未保存      第 18 行      12 个问题 · 3 个待人工核实       │
└──────────────────────────────────────────────────────────────────┘
```

- 默认浅色：`#F6F7F8` 应用背景、`#FFFFFF` 编辑面、`#D8DEE4` 分隔线、`#1F2328` 正文、`#667085` 次要文字；使用单一蓝色作为交互强调，橙/红仅表达警告和错误。
- 顶栏 44–48px；底部状态栏 24–28px；主区用可拖动分隔线，编辑区约 62%，审查栏约 38%。
- 设置抽屉容纳 Base URL、API Key、模型和隐私说明；关闭后只显示“模型已配置/未配置”。
- 问题行高度约 48–64px，包含严重度图标、规则名、单行摘录和位置；支持按“全部/可改写/待核实”过滤。
- 选中问题后才显示原因、上下文和接受/忽略操作；全文修订使用 GitHub Desktop 式统一/并排 diff。
- 删除所有英文 eyebrow、发光状态点和装饰性编号。保留一个产品标识即可，不使用渐变徽标。

### 实施顺序

1. **P0：重排外壳。** 删除步骤条；把连接配置移入设置抽屉；建立顶栏、编辑区、审查栏、状态栏四区。
2. **P0：替换视觉令牌。** 改为纯色浅色主题，统一 4/8/12/16px 间距、4–6px 圆角、12px 元信息下限；移除渐变、发光和常驻阴影。
3. **P1：重做结果交互。** 卡片改成问题行 + 选中项详情；问题与正文位置双向定位。
4. **P1：加入真实 diff。** 语义复核后默认进入统一 diff，可切并排；每个改动逐项接受/拒绝，最后再应用全文。
5. **P2：补充桌面品质。** 可拖动面板、键盘导航、浅/深主题和紧凑/舒适密度。

## 许可与品牌注意事项

- **VS Code** 源码为 [MIT](https://github.com/microsoft/vscode/blob/main/LICENSE.txt)。可借鉴布局原则；不要复制 Microsoft/Visual Studio Code 名称、图标或产品 trade dress。
- **GitHub Desktop** 为 [MIT](https://github.com/desktop/desktop/blob/development/LICENSE)，但其 [README 明确说明 GitHub 商标和 logo 不在 MIT 授权内](https://github.com/desktop/desktop#license)。只复用 diff/列表交互原则。
- **Joplin** 默认代码许可为 [AGPL-3.0-or-later，且商标、logo、icon 另有限制](https://github.com/laurent22/joplin/blob/dev/LICENSE)。不要复制源码、图标或主题实现；仅提炼抽象布局和隐私表达。
- **Zettlr** 为 GPLv3，且 [README 明确排除名称、图标等品牌资产](https://github.com/Zettlr/Zettlr#license)。不要直接搬用源码或品牌元素。
- **Zed** 代码主要为 [GPL-3.0-or-later，部分文件另标 Apache-2.0](https://github.com/zed-industries/zed#licensing)。不要复制实现；密度、字体分层和面板停靠仅作为设计原则参考。

WenLint 当前是 MIT 项目。为了保持许可边界清晰，本次改版应自行编写 Vue/CSS，不导入上述项目的源码、图标、截图、字体文件或品牌资产。
