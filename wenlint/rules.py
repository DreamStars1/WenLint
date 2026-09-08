"""WenLint 规则定义（规则引擎 v0.1）。

Rule 结构：
    id          规则 ID（C001 套话 / H001 模糊 / M001 过程痕迹 /
                 M002 上下文依赖 / E001 强调 / R001 冗余 / D001 重复 /
                 S001 长句 / A900 文件结构 / DOC001 空标题 /
                 DOC002 编号断层）
    name        英文名
    category    中文类别
    severity    warning | suggestion（semantic 规则命中运行时降为 candidate）
    patterns    触发词/正则（同一规则内 OR）
    block       排除正则（命中则不报，如"由此可见一斑"）
    semantic    True = 规则判不了，命中降级 candidate 交 LLM 语义层裁决
    message     命中提示（{w} = 命中的词）
    review_hint 给 Skill/LLM 的审查指导——判断这条命中该怎么处理
                （查证方向 / 保留条件 / 改写建议），避免每次重新理解规则

架构原则：WenLint 只负责"发现"（定位 + 规则 ID + 命中文本 + 上下文 +
审查提示），**不做任何语言修复**；判断/查证/改写全部由 Skill 的 LLM 完成。
"""

RULES = [
    # ---------- C: 套话 / 废话填充 ----------
    {
        "id": "C001", "name": "cliche-intro", "category": "套话/废话填充",
        "severity": "warning", "message": "套话「{w}」，删掉更直接",
        "patterns": ["总而言之", "综上所述", "值得注意的是", "众所周知",
                     "毋庸置疑", "不难发现", "需要注意的是", "换句话说"],
        # 词后接"的/之/地"是定语结构（"综上所述的方案"），删词破坏句法——不报；
        # 其余（和/与/及/并且）会误豁免正常句子（"值得注意的是和用户沟通…"），
        # 只保留明确的句法例外，元语境交给语义层判 KEEP
        "block": r"(总而言之|综上所述|值得注意的是|众所周知|毋庸置疑|"
                 r"不难发现|需要注意的是|换句话说)(的|之|地)",
        "review_hint": "句首引导性套话，多数可直接删除且语义无损。"
                       "例外：若词后接'的/之/地'（如'综上所述的方案'）或处于引述中，"
                       "删除会破坏句法或语义，应保留并说明。",
    },
    {
        "id": "C002", "name": "buzzword", "category": "套话/废话填充",
        "severity": "warning", "message": "术语滥用「{w}」，换成大白话",
        "patterns": ["赋能", "抓手", "闭环", "颗粒度", "底层逻辑",
                     "顶层设计", "多维度", "全链路", "保驾护航"],
        "semantic": True,
        "review_hint": "判断该词是否领域正当术语：'处置闭环/反馈闭环/诊后闭环'"
                       "等有实际闭环对象的是术语（KEEP）；'打造闭环/思维赋能'"
                       "等无实指对象的是空话（REWRITE 成大白话）。"
                       "若出现在引述/引用他人原话中则不改。",
    },
    {
        "id": "C003", "name": "cliche-由此可见", "category": "套话/废话填充",
        "severity": "warning", "message": "套话「{w}」，删掉更直接",
        "patterns": ["由此可见"],
        "block": r"由此可见(一斑|的|之|地|和|与|及)",
        "review_hint": "同 C001：推理衔接套话，删后若前后句仍连贯则可删；"
                       "'由此可见一斑'是成语习语不报（规则已排除）。",
    },
    # ---------- H: 模糊词 ----------
    {
        "id": "H001", "name": "hedge-hard", "category": "模糊词",
        "severity": "warning", "message": "模糊词「{w}」，表述要精确",
        "patterns": ["大概", "好像", "似乎", "差不多"],
        "review_hint": "判断该句是否含可被事实核实的陈述：若是（时间/数量/"
                       "能力/归因），先检索资料——找到依据则 REWRITE 成确定表述并附依据；"
                       "找不到则 ASK 作者。若是推测/口语则 KEEP。",
    },
    {
        "id": "H002", "name": "hedge-soft", "category": "模糊词",
        "severity": "suggestion",
        "message": "模糊词「{w}」——论文/技术文档中如需保留学术审慎可忽略",
        "patterns": ["可能", "或许", "也许", "大约", "一定程度上", "某种程度"],
        "semantic": True,
        "review_hint": "最高频语义判断：'可能'多数是合理的风险提示/条件表达/"
                       "学术审慎（KEEP，不删）；只有对可从资料核实的事实断言"
                       "（'系统可能支持 X'）才去检索——找到依据 REWRITE，"
                       "找不到 ASK，绝不在无依据时直接删除不确定词。",
    },
    {
        "id": "H003", "name": "hedge-左右", "category": "模糊词",
        "severity": "suggestion", "message": "「左右」歧义：时间/数量约数 or 空间方位？",
        "patterns": ["左右"],
        "block": r"左右(两边|两侧|两翼|左右|边|侧|手|翼|前后|上下)",
        "semantic": True,
        "review_hint": "看语境区分：数字后（'3 米左右'）是约数，若可核实则查资料"
                       "给精确值（REWRITE）；空间方位（'左右手/左右边'）已被规则"
                       "排除；指方向时（'左右局势'）是动词用法，KEEP。",
    },
    # ---------- M: 成稿中的讨论史 / 旧上下文依赖 ----------
    {
        "id": "M001", "name": "revision-history", "category": "过程痕迹",
        "severity": "suggestion",
        "message": "过程性表述「{w}」——核对成稿是否夹带讨论或纠偏历史",
        "patterns": ["讨论过程", "经过讨论", "经讨论", "讨论后",
                     "纠偏说明", "纠偏", "纠正", "修正", "更正",
                     "改为", "改成", "恢复为", "原先", "此前", "先前"],
        "semantic": True,
        "review_hint": "核对这句话是在陈述当前有效结论，还是记录讨论、纠偏或版本演变过程。"
                       "若过程本身是审计记录、决策日志或迁移说明的必要内容则 KEEP；"
                       "若最终交付稿只需表达现状，应 REWRITE 为自洽的当前结论。"
                       "无法从本文或可追溯资料确认当前基线时 VERIFY，仍不足则 ASK。",
    },
    {
        "id": "M002", "name": "context-dependent-transition",
        "category": "上下文依赖", "severity": "suggestion",
        "message": "上下文依赖表述「{w}」——核对顺序、旧状态或比较基线是否完整",
        "patterns": ["不再", "仍然", "仍旧", "依然",
                     r"先[^。！？；;\n]{0,40}(?:再|然后)"],
        "semantic": True,
        "review_hint": "结合前后句、相关章节和依据核对指代与基线。"
                       "'先…再/然后…'若在当前稿内给出完整步骤且顺序明确则 KEEP；"
                       "'不再/仍然/仍旧/依然'若没有交代旧状态、时间点或比较对象，"
                       "应 VERIFY/ASK，确认后改写为不依赖旧上下文的当前规则。",
    },
    # ---------- E: 空洞强调 ----------
    {
        "id": "E001", "name": "empty-emphasis", "category": "空洞强调",
        "severity": "suggestion", "message": "空洞强调「{w}」，删除或换成具体描述",
        "patterns": ["非常", "十分", "极其", "超级", "真的", "简直",
                     "绝对", "毫无疑问"],
        "review_hint": "判断强调是否有实际内容支撑：能给出具体程度/数据/"
                       "例证则保留或替换成具体描述；纯语气填充则删除。"
                       "口语/对话场景可放宽（KEEP）。",
    },
    # ---------- R: 冗余结构 ----------
    {
        "id": "R001", "name": "redundant-verb", "category": "冗余结构",
        "severity": "suggestion",
        "message": "「{w}」冗余——动词直接说即可（进行+分析 → 分析）",
        "patterns": [r"进行(?=(分析|讨论|研究|说明|处理|调查|测试|验证))"],
        "review_hint": "'进行 + 动词'是典型书面冗余，直接改动词即可（'进行分析'"
                       "→'分析'），语义无损（REWRITE）。若'进行'不后接动名词"
                       "（如'实验正在进行'）规则不会命中。",
    },
    {
        "id": "R002", "name": "wordy-是否能够", "category": "冗余结构",
        "severity": "suggestion", "message": "「是否能够」→「能否」",
        "patterns": ["是否能够"],
        "review_hint": "固定缩短：'是否能够'→'能否'，语义不变（REWRITE）。",
    },
    # ---------- D: 重复 ----------
    {
        "id": "D001", "name": "duplicate-word", "category": "重复用词",
        "severity": "warning", "message": "「{w}」连续重复",
        "patterns": [],
        "review_hint": "相邻重复词多数是笔误/口误，去掉一个即可（REWRITE）；"
                       "若是有意的强调或歌词/口号类重复则 KEEP。",
    },
    # ---------- S: 句子结构 ----------
    {
        "id": "S001", "name": "long-sentence", "category": "超长句",
        "severity": "suggestion", "message": "句子过长（{len}字 > {max}），建议拆分",
        "max_len": 80,   # 文档默认 80；SKILL.md（instruction profile）收紧到 50
        "review_hint": "长句拆分：找出句内的逻辑断点（并列/转折/因果）拆成 2-3 句，"
                       "保持信息不丢失。注意只改 WenLint 指出的句子，不要全文润色。",
    },
    # ---------- A: 文件结构（文件级规则）----------
    {
        "id": "A900", "name": "god-file", "category": "文件结构",
        "severity": "suggestion",
        "message": "SKILL.md 主文件过长（{len} 行 > {max}）——细节应拆到 references/ 子文件，主文件只留触发条件/快速上手",
        "max_lines": 300,
        "review_hint": "结构性问题：把主文件中的详细流程/案例/历史教训按主题移到"
                       "references/ 子文件，主文件保留触发条件/快速上手/红线速览/"
                       "导航。移动是机械操作（REWRITE），但注意保持引用完整。",
    },
    # ---------- DOC: 文档结构（标题；不可自动写回）----------
    {
        "id": "DOC001", "name": "empty-heading", "category": "文档结构",
        "severity": "warning",
        "message": "空标题：删除该标题或补齐标题文本",
        "patterns": [],
        "review_hint": "结构问题：空 ATX/投影标题没有可见文本。删除空标题，或补上明确标题；"
                       "不可自动写回，由作者确认。",
    },
    {
        "id": "DOC002", "name": "numbered-heading-gap", "category": "文档结构",
        "severity": "candidate",
        "message": "标题编号可能断层：前一为「{prev}」，当前为「{curr}」，请核对是否缺章",
        "patterns": [],
        "review_hint": "仅提示同一父标题下、同级、显式阿拉伯数字编号向前跳号。"
                       "允许作者有意预留章节，故为 candidate；不可自动写回。",
    },
]


def by_id(rid):
    """按 ID 查规则。

    Args:
        rid: 规则 ID（如 "H002"）。

    Returns:
        dict 或 None：规则定义；未找到返回 None。
    """
    for r in RULES:
        if r["id"] == rid:
            return r
    return None
