---
name: wenlint
description: 检查中文文档写作/检测 AI 味时使用。文尺 WenLint：像 ESLint 一样的中文写作静态检查器（规则 ID + profile + 安全 fix）。
---

# 文尺 WenLint：中文写作静态检查器

像 ESLint 检查代码一样检查中文 PRD、论文、报告和 Markdown。确定性规则引擎（词法模式/套话/模糊词/冗余/长句），不是"AI 味扫描器"。

## 何时使用

- 用户写完中文文档/PRD/论文/报告，要求"检查写作/有没有 AI 味/用词问题"
- 检查 AI 生成内容的质量（对外交付的文档尤其需要）
- 用户提到 wenlint / 文尺 / prose lint / 中文写作检查

## 执行原则（先查找，后询问）

用户没指明具体文件时，按顺序自行定位，不要问"检查哪个文件"：
1. 工作区/家目录最近的 .md 文档（~ 文档、PRD、论文调研、当前工作目录）
2. 代码库内 markdown（README/docs/AGENTS.md；用 search_files 找含套话词的文件）
3. 网络内容：用户给 URL，或能 web 搜索定位的文档/知识（提到某文章/标准先自己搜）
4. 定位不到或歧义大（多个候选）才询问用户

默认 review（只报告不改）；用户明确要改才 --fix。

## 安装与运行

```bash
pip install -e <repo_path>       # 一次性安装，获得 wenlint 命令
# 或免安装： cd <repo_path> && python -m wenlint <path>
```

```bash
wenlint 文档.md                    # review
wenlint . --profile academic       # 论文场景
wenlint README.md --fix            # 修复预览（不写盘）
wenlint README.md --fix --apply    # 写回（先备份 .bak）
wenlint . --fail-level warning     # CI：有 >= warning 时 exit 1
```

## 输出格式

`文件:行:列  规则ID  级别  类别  message`

```
README.md:18:7  C001  warning  套话/废话填充  套话「总而言之」，删掉更直接
```

## 规则速查

- **C001** 套话引导词（`总而言之/综上所述…，可自动删`）
- **C002** 术语滥用（`赋能/抓手/闭环…`）
- **H001** 模糊词硬（`大概/好像/差不多`）；**H002** 模糊词软（`可能/或许`，academic profile 关闭）
- **E001** 空洞强调（`非常/真的…`）；**R001** 冗余动词（进行+动词）
- **D001** 相邻重复词；**S001** 超长句（`>60 字，academic 80`）

## 安全规则（fix）

**自动改**（高置信白名单 C001/C003/R002）：删除套话引导词（词后接逗号/句读/行尾时）
**绝不自动改**：定语结构（`综上所述的方案`）、引号/代码内、模糊词、重复词、超长句（fix 后列出）

## 两段式（对 LLM 协作的定位）

本工具是**第一层 deterministic lint**：快、可解释、可 CI。
语义级问题（逻辑跳跃/段落重复/论证空洞）属**第二层 semantic review**（LLM）。
两者输出必须分开，不要把 LLM 判断包装成 lint warning。
