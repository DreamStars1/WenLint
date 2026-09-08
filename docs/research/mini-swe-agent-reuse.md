# mini-swe-agent 复用于 WenLint 桌面工作区审查 Agent 的可行性研究

> 研究日期：2026-09-08  
> mini-swe-agent 源码基线：[`04d809ceab9df28f9adaed044884180159172930`](https://github.com/SWE-agent/mini-swe-agent/tree/04d809ceab9df28f9adaed044884180159172930)  
> 发布基线：PyPI `2.4.6`（2026-07-23）  
> 证据范围：官方 GitHub 仓库源码与仓库内文档、官方 GitHub 发布页、PyPI 发布元数据、仓库许可证。未采用第三方教程、博客或二手解读。

## 结论

mini-swe-agent **适合复用控制流思想和少量核心代码，不适合把完整包直接嵌入 WenLint EXE，也不应复用其默认本地执行环境**。

推荐方案是：以 MIT 许可下的 `DefaultAgent` 为参考或小范围 vendoring，保留“模型请求 → 工具执行 → 观察回填 → 继续/退出”的线性循环、消息轨迹和限额概念；由 WenLint 自己实现精简的 OpenAI-compatible function-calling 适配器，以及严格受工作区约束的只读工具环境。修改文件必须继续走 WenLint 现有的“预览差异 → 用户确认 → 内容哈希校验 → 原子写回”，不能让模型直接获得 shell 或任意写文件能力。

不建议直接依赖 `mini-swe-agent` 包的主要原因是：

1. 它的默认工具只有一个高权限 `bash(command)`，无法表达 WenLint 所需的细粒度读文件、搜索、提交审查结果与提议修改；解析器还把工具名硬编码为 `bash`。[工具定义与解析](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/models/utils/actions_toolcall.py#L11-L76)
2. 本地环境通过 `shell=True` 直接在宿主机执行模型生成的命令，官方文档也明确标注它“无隔离”。这与面向普通用户的桌面审查工具安全边界不相容。[本地执行源码](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/environments/local.py#L19-L43)；[环境说明](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/advanced/environments.md#L10-L31)
3. 完整包的基础依赖包含 LiteLLM、OpenAI SDK、Textual、Datasets、Rich、Typer、Prompt Toolkit 等；WenLint 当前核心运行时无依赖，桌面版只额外引入 pywebview。整体接入会显著扩大 EXE 依赖面、体积和冻结复杂度。[mini-swe-agent 依赖](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/pyproject.toml#L33-L48)
4. ReAct 每多读一次文件通常就多一次模型往返。对短文或无需旁证的审查，它可能比 WenLint 当前一次/两次模型调用更慢。因此工作区 Agent 应是**按需触发的受限深度复核**，而不是所有审核的固定前置步骤。

## 1. 研究基线与版本状态

当前仓库源码在 `minisweagent.__version__` 中声明版本 `2.4.6`；PyPI 的最新稳定发布也是 `2.4.6`，要求 Python `>=3.10`，发布物为通用 Python wheel 和源码包。[源码版本](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/__init__.py#L11-L18)；[PyPI 2.4.6 发布元数据](https://pypi.org/project/mini-swe-agent/2.4.6/)

仓库将项目标记为 Alpha，并声明操作系统无关；这表示其 Python 包元数据没有限定平台，但不等于默认提示词、shell 行为或 PyInstaller 冻结已经针对 Windows 桌面产品验证。[项目元数据](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/pyproject.toml#L6-L30)

值得注意的是，仓库部分说明仍保留 v1 的描述：FAQ 称动作来自反引号代码块且“不使用模型 tool calling”，而当前 v2 默认配置 `mini.yaml`、`LitellmModel` 和模型参考页实际采用原生 function calling。实施判断应以当前固定提交的代码和 v2 配置为准。[FAQ 的旧描述](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/faq.md#L29-L50)；[v2 默认配置](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/config/mini.yaml#L111-L151)；[模型类型表](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/reference/models/overview.md#L5-L20)

## 2. Agent / ReAct 主循环

### 2.1 核心流程

`DefaultAgent.run()` 先重置消息列表，加入 system 与 user 两条初始消息，然后循环执行 `step()`；`step()` 等价于 `execute_actions(query())`。每轮流程如下：[Agent 主循环源码](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py#L88-L157)；[官方控制流文档](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/advanced/control_flow.md#L12-L45)

```text
system + task
    ↓
Model.query(全部历史消息)
    ↓
解析一个或多个 tool call
    ↓
Environment.execute(action)（逐个、同步执行）
    ↓
将 stdout / returncode / exception_info 格式化为 observation
    ↓
追加到线性消息历史
    ↓
下一轮，或收到 exit 消息后结束
```

这是标准的“行动—观察—再行动”循环，但实现刻意很薄：Agent 不做规划树、任务队列、文件选择策略或历史摘要，选择下一步完全交给模型。`execute_actions()` 对同一响应中的多个动作使用列表推导顺序执行，并非并发执行。[动作执行](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py#L126-L157)

### 2.2 组件边界

项目通过三个很小的 Protocol 分离 Agent、Model 与 Environment；运行时主要依靠鸭子类型。官方 cookbook 也把扩展方式定义为选择/继承 Agent、Environment、Model，再由 run script 组装。[Protocol 定义](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/__init__.py#L39-L80)；[官方扩展指南](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/advanced/cookbook.md#L13-L28)

这部分非常适合 WenLint：可以保留同样的三个边界，但把 `Environment` 改成 `WorkspaceToolEnvironment`，把 `Model` 改成现有轻量 OpenAI-compatible 客户端，把返回值改成 WenLint 的结构化审查报告。

## 3. 默认与可选工具、调用协议

### 3.1 当前默认工具

当前 v2 默认模型请求只注册一个函数：

```json
{
  "type": "function",
  "function": {
    "name": "bash",
    "parameters": {
      "type": "object",
      "properties": {"command": {"type": "string"}},
      "required": ["command"]
    }
  }
}
```

`LitellmModel` 将该定义作为 `tools=[BASH_TOOL]` 发送给 `/completion` 风格接口；Responses API 变体发送扁平化的等价工具定义。解析器要求至少存在一个工具调用，只接受工具名 `bash`，将 JSON 参数转成 `{"command": ..., "tool_call_id": ...}`。[Chat Completions 工具调用](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/models/litellm_model.py#L64-L105)；[Chat Completions 解析器](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/models/utils/actions_toolcall.py#L11-L76)；[Responses API 定义与解析](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/models/utils/actions_toolcall_response.py#L10-L25)

工具执行结果以 `tool` 消息回传，关联原来的 `tool_call_id`；默认观察内容包含命令返回码、stdout 和异常信息，额外元数据保存原始输出与时间戳。[观察消息格式化](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/models/utils/actions_toolcall.py#L79-L113)

### 3.2 可选项究竟是什么

mini-swe-agent 没有内置 `read_file`、`search`、`edit_file`、`git` 或 `submit` 等独立工具；这些能力都由模型拼成 shell 命令。官方提供的“可选”主要是：

- **调用协议**：LiteLLM/OpenRouter 的 Chat Completions function calling、Responses API function calling，或兼容弱模型的文本正则动作格式。[模型类型表](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/reference/models/overview.md#L5-L20)；[文本动作解析](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/models/litellm_textbased_model.py#L7-L47)
- **执行后端**：local、Docker、Singularity，以及额外的 SWE-ReX Docker/Modal、Bubblewrap、ConTree。它们替换命令执行位置，不改变“只有 bash 命令”这一动作抽象。[环境注册表](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/environments/__init__.py#L8-L33)
- **Agent 模式**：DefaultAgent 与 InteractiveAgent。CLI 默认组合是 `mini.yaml + local environment + InteractiveAgent`；InteractiveAgent 提供 human/confirm/yolo 三种确认模式和命令白名单，但没有增加业务工具。[CLI 组装](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/run/mini.py#L92-L103)；[交互模式](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/interactive.py#L1-L30)

官方 cookbook 演示了通过继承 Agent 或 Environment，把特殊命令路由到 Python 函数。这证明控制流可扩展，但其示例仍把“工具选择”编码在 `command` 字符串前缀中，不是通用多函数注册表。[自定义执行示例](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/advanced/cookbook.md#L122-L177)

## 4. 上下文、观察、退出与错误处理

### 4.1 上下文与观察

- 历史是完全线性的：system、task、assistant tool call、tool observation 不断追加；每次查询都把完整 `self.messages` 交给模型，没有内置摘要、裁剪或检索记忆。[完整历史传入模型](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py#L69-L72)；[query 实现](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py#L130-L152)
- 默认 v2 配置仅对**单次命令输出**做裁剪：超过 10,000 字符时保留前后各 5,000 字符。原始输出仍保存在消息的 `extra.raw_output` 中并进入轨迹文件，但在发给模型前会移除 `extra`。[观察裁剪模板](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/config/mini.yaml#L112-L128)；[API 消息清理](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/models/litellm_model.py#L76-L79)
- 每轮在 `finally` 中保存轨迹；序列化内容包含模型统计、配置、退出状态和完整消息列表。[轨迹保存](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py#L159-L190)

对 WenLint 的影响：按需读取确实避免了启动时发送全工作区，但如果不断读文件，内容仍会累积在历史中。WenLint 必须另加“总读取文件数、总字符数、每文件片段长度、模型轮次”预算，并对 observation 做片段级裁剪；否则只是把一次大上下文变成逐轮增长的大上下文。

### 4.2 正常退出

默认 LocalEnvironment 把 stdout 去除前导空白后的第一行识别为魔术字符串 `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`，且命令返回码为 0 时抛出 `Submitted`；后续输出作为 submission。Agent 捕获该控制流异常，把携带 `role=exit` 的消息加入历史，然后结束循环。[退出检测](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/environments/local.py#L45-L56)；[退出循环](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py#L96-L124)

WenLint 不应复用魔术 stdout 字符串，应定义强类型的 `submit_review` function：参数包含摘要、发现、证据位置和建议修改；模型调用它即结束。这样无需 shell，也更容易做 schema 校验和 UI 呈现。

### 4.3 限额与错误

- Agent 在每次模型查询前检查步数、累计费用和墙钟时间；默认步数无限、费用上限 3 美元、墙钟无限。[限额配置](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py#L19-L35)；[查询前检查](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py#L130-L150)
- function call 缺失、未知工具、参数 JSON 错误或缺少 `command` 会形成 `FormatError` observation 反馈给模型；默认连续 3 次格式错误后以 `RepeatedFormatError` 退出，成功一步会清零计数。格式错误调用产生的费用仍会累计。[格式错误解析](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/models/utils/actions_toolcall.py#L30-L76)；[Agent 处理](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py#L96-L119)
- 模型层默认最多重试 10 次，指数等待 4–60 秒；认证、权限、模型不存在、参数不支持、上下文溢出等列入立即终止异常。这个默认值对桌面交互可能造成很长的尾部等待。[重试策略](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/models/utils/retry.py#L9-L25)；[立即终止异常](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/models/litellm_model.py#L49-L57)
- LocalEnvironment 捕获命令执行异常并把它变成 `returncode=-1` 的观察，因此模型可以自行纠偏；命令默认超时 30 秒。[本地环境错误处理](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/environments/local.py#L13-L43)
- 未被视为 Agent 控制流的异常会先记录 exit/traceback，再重新抛出；轨迹仍在 `finally` 中保存。[未捕获异常处理](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py#L74-L124)

WenLint 应将重试缩到 1–2 次并设置整次审核硬截止时间；工具错误作为结构化、可纠正的 observation 返回；认证失败、上下文溢出和用户取消应立即退出。墙钟预算还需覆盖正在进行的模型请求和工具调用，而不是只在下一轮开始前检查。

## 5. Python 依赖、可嵌入性与 Windows/EXE 风险

### 5.1 可嵌入性

有利条件：

- 核心 Agent 很小，Model/Environment/Agent 的接口窄，并且官方直接提供 Python bindings 和 subclassing 用法。[Python bindings](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/usage/python_bindings.md#L8-L28)
- 发布物是 `py3-none-any` wheel，要求 Python `>=3.10`；WenLint 要求 Python `>=3.11`，解释器版本兼容。[PyPI 2.4.6](https://pypi.org/project/mini-swe-agent/2.4.6/)
- 核心组件由配置与工厂组装，也允许传入完整 import path 的自定义类。[Agent 工厂](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/__init__.py#L8-L28)；[模型动态加载](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/models/__init__.py#L78-L113)

不利条件：

- 基础安装并不“只含 100 行 Agent”，而是无条件依赖 15 个顶层包，包括较重、动态行为较多的 LiteLLM、Datasets、Textual 和 OpenAI SDK。[依赖清单](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/pyproject.toml#L33-L48)
- 类工厂使用 `importlib.import_module` 动态加载 Agent、Model、Environment；这是冻结工具通常需要显式收集 hidden imports 的模式。包还依赖 YAML/T CSS 等数据文件和 Jinja 模板。[动态环境加载](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/environments/__init__.py#L8-L33)；[包数据](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/pyproject.toml#L95-L106)
- 导入顶层包会创建用户配置目录、打印启动信息并加载 `.env`。嵌入 GUI 时属于不必要的导入副作用，也可能与 WenLint 自己的密钥存储策略冲突。[导入副作用](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/__init__.py#L23-L36)

因此，“安装整个包再从 EXE 导入”技术上可行，但不是 WenLint 的优选集成方式。更稳妥的是 vendoring 经过裁剪的循环/异常概念，继续使用 WenLint 当前轻量 HTTP 客户端；这也避免为了一个工作区循环引入完整 CLI、TUI、数据集和多供应商栈。

### 5.2 Windows 与安全风险

以下判断由固定提交源码直接推导：

1. **提示词与运行环境不一致。** 官方 FAQ 要求系统存在 bash，默认提示词给出 `sed`、`cat`、heredoc 等 POSIX 示例；但 LocalEnvironment 在 Windows 上使用 `shell=True`，实际 shell 通常由 Windows 运行时选择，不能假设这些命令存在。[系统要求](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/faq.md#L5-L8)；[默认命令示例](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/config/mini.yaml#L55-L100)；[进程启动](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/environments/local.py#L72-L85)
2. **超时只可靠终止直接进程。** POSIX 分支创建并杀死进程组；Windows 分支调用 `process.kill()`，源码没有遍历并清理子进程树。[超时处理](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/environments/local.py#L72-L92)
3. **默认 local 无沙箱。** 模型命令继承宿主进程环境变量，并可访问当前用户有权限的文件和网络；这会扩大提示注入、误删文件和密钥泄漏风险。[环境变量与执行](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/environments/local.py#L24-L30)
4. **InteractiveAgent 面向终端。** confirm/human 模式通过 stdin、Prompt Toolkit 和终端输出交互，不能直接映射为 pywebview 的异步确认体验。[终端交互](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/interactive.py#L58-L107)

WenLint 当前已有更合适的工作区边界：只接受用户选择的根目录；相对路径解析后必须仍在根目录内；拒绝符号链接/目录联接；只读受支持的文本后缀；单文件限制 2 MB；写入需要用户确认和预期 SHA-256，并通过同目录临时文件原子替换。这些约束应成为 Agent 工具实现的底座，而不是被 shell 绕过。

## 6. 许可证与直接复用条件

mini-swe-agent 使用 MIT License。许可允许使用、复制、修改、合并、发布、分发、再许可和销售；条件是所有软件副本或实质性部分保留原版权声明和许可声明，且作者不提供担保并免责。[完整许可证](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/LICENSE.md#L1-L21)

对 WenLint 的实际要求：

- 若复制 `DefaultAgent`、tool-call 解析器或其他可识别的实质性代码，应在 WenLint 的第三方声明/NOTICE 中加入 mini-swe-agent 的版权与 MIT 全文，并在 vendored 文件头标明来源提交与修改情况。
- 若仅借鉴抽象思想、完全独立实现，通常不构成复制代码；为了可追溯性，仍建议在架构文档中注明设计参考。
- MIT 不要求 WenLint 整体改用 MIT，也不要求公开衍生源码，但不能移除上游版权和许可声明。
- 发布 EXE 时许可文本也应随二进制分发，例如放入“关于/第三方许可”和安装目录中的 `THIRD_PARTY_NOTICES.txt`。

## 7. 可直接复用与必须改造的边界

| 上游部分 | 建议 | 理由 / WenLint 改造点 |
| --- | --- | --- |
| `DefaultAgent.run/step/query/execute_actions` 的控制流 | **小范围复用或等价重写** | 结构简单、可测试，适合 ReAct；需加入取消、事件回调、整次硬超时、工具/字符预算和结构化最终结果。 |
| Agent / Model / Environment 三接口 | **直接复用思想** | 能让 GUI、模型供应商和工作区工具解耦；WenLint 可用更窄的本地 Protocol，避免导入上游包。 |
| 线性 messages/trajectory | **部分复用** | 便于调试和用户查看过程；必须裁剪 observation、脱敏密钥，并限制持久化内容。 |
| `InterruptAgentFlow`、`FormatError`、`LimitsExceeded` | **可复用概念** | 适合统一退出原因；GUI 中应转换为明确状态，不应依赖异常携带任意消息作为全部状态机。 |
| LiteLLM `LitellmModel` | **不直接复用** | 依赖重、默认重试过长；WenLint 已有 OpenAI-compatible 请求层，还需 DeepSeek 的非思考/JSON 配置和稳定超时。 |
| `actions_toolcall.py` | **参考后重写** | 只认识 `bash`。WenLint 需要通用 registry、每个函数独立 schema、参数校验和权限分类。 |
| `LocalEnvironment` | **禁止复用** | 任意 shell、无隔离、继承环境变量，不符合桌面文档审查安全边界。 |
| Docker/SWE-ReX/Bubblewrap/ConTree | **首版不复用** | 对只读文档检索过重，并增加安装和平台要求；WenLint 现有受限文件 API 已足够。 |
| `InteractiveAgent` | **不直接复用** | stdin/终端确认模型与 Vue/pywebview 不匹配；保留其“危险操作需确认”原则，在 GUI 事件层重新实现。 |
| Jinja/YAML 配置体系 | **首版不复用** | WenLint 工具和提示固定且少，增加依赖与用户配置复杂度；可用 Python 数据结构和版本化 prompt。 |
| 魔术字符串退出 | **改成 `submit_review`** | function schema 可校验，能够直接生成 WenLint 报告、差异和修改原因。 |

## 8. WenLint 所需工具与建议协议

### 8.1 首版最小工具集

建议不要提供通用 shell。首版只暴露以下函数：

| 工具 | 作用 | 关键约束 |
| --- | --- | --- |
| `list_workspace_files` | 按前缀/后缀列出候选文本文件 | 最多返回 100 项；忽略隐藏、生成、vendor 目录；不返回正文。 |
| `read_workspace_text` | 按需读取一个文件或指定行段 | 复用 `WorkspaceSession` 路径校验；每次最多 20–40 KB；限制总文件数和总字符数。 |
| `search_workspace_text` | 在允许的文本文件中搜索关键词/短语 | 返回路径、行号和短上下文；结果上限；不允许任意正则造成灾难性回溯。 |
| `get_static_findings` | 获取当前文档的 WenLint 规则命中 | 本地执行，不调用模型；返回压缩字段。 |
| `submit_review` | 提交摘要、新发现、关联证据和修改提案并结束 | 严格 JSON Schema；引用必须指向已读文件/当前文档；由本地验证后进入 UI。 |

写操作不应成为同一轮 Agent 的常规工具。模型只在 `submit_review` 中提交候选补丁或替换建议；GUI 展示修改原因、前后变化和上下文。用户确认后，继续调用 WenLint 现有写入 API完成哈希校验和原子落盘。

### 8.2 建议主循环

```text
输入：当前文档正文 + 压缩静态命中 + 当前文件相对路径
  ↓
模型可直接 submit_review
  或调用 list/search/read（仅在需要旁证时）
  ↓
本地校验并执行只读工具，回填短 observation
  ↓
最多 2–4 个工具轮次、最多 N 个文件/字符、整次硬超时
  ↓
submit_review → 本地验证引用/范围/补丁 → GUI 展示
  ↓
用户选择接受/撤销/保存；写入不由 Agent 自主执行
```

为了响应速度，应采用混合策略：当前待审文档仍随初始请求发送；不再发送最多 30,000 字符的全量工作区路径上下文。只有模型明确需要旁证时才调用目录与读取工具。普通审查可零工具轮次完成；深度审查才进入 ReAct。这样既实现“模型自己选择读哪些文件”，又避免为每篇短文强制增加多次模型往返。

### 8.3 必须增加的产品级约束

- 默认只读；任何落盘都由用户在 GUI 中逐项或批量确认。
- 每轮工具 schema 校验；未知工具、越界路径、超限输出作为可纠偏 observation 返回。
- 单次审核建议默认：最多 4 次模型调用、读取最多 6 个文件、工作区 observation 总量不超过 80–120 KB、总墙钟 45–60 秒；具体数值需用真实模型压测后确定。
- 支持取消信号、分阶段进度和每轮耗时，避免 mini-swe-agent 默认 10 次网络重试造成不可感知的长等待。
- 对工作区文件内容视为不可信数据：系统提示明确声明文件内指令不可改变工具权限或审查目标；工具层仍以代码约束权限，不能只靠提示词。
- 轨迹默认只保存在内存；若用户导出，需提示其中可能包含文档内容，并确保 API Key、Authorization 头和客户端配置永不进入轨迹。

## 9. 最终建议

采用“**mini-swe-agent-inspired, WenLint-native**”路线：

1. 不把 `mini-swe-agent` 加入运行时依赖。
2. 参考或在 MIT 条件下摘取 `DefaultAgent` 的小型循环、消息轨迹和错误分类。
3. 独立实现约 5 个 WenLint function tools，并让工具注册表驱动 schema、参数验证和执行。
4. 基于现有 `WorkspaceSession` 实现只读环境，禁止 shell、绝对路径、符号链接和未经确认的写入。
5. 用 `submit_review` 代替魔术字符串，输出新发现、修改原因、变化和证据。
6. 将 Agent 工作区读取作为“深度复核”能力；普通审查保持单轮快速路径。
7. 在决定复制任何上游代码时添加第三方 MIT 声明，并固定记录来源提交。

这条路线保留了 mini-swe-agent 最有价值的部分——极小、线性、可观察的 ReAct 循环——同时避开它为软件工程终端 Agent 设计的任意 shell、安全边界、依赖体积和 Windows 交互假设。

## 一手资料索引

- [官方仓库固定提交](https://github.com/SWE-agent/mini-swe-agent/tree/04d809ceab9df28f9adaed044884180159172930)
- [DefaultAgent](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/agents/default.py)
- [Tool-call 模型与 bash 工具协议](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/models/litellm_model.py)
- [LocalEnvironment](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/environments/local.py)
- [官方控制流文档](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/advanced/control_flow.md)
- [官方扩展 cookbook](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/advanced/cookbook.md)
- [项目依赖与元数据](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/pyproject.toml)
- [PyPI 2.4.6 发布元数据](https://pypi.org/project/mini-swe-agent/2.4.6/)
- [MIT License](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/LICENSE.md)
