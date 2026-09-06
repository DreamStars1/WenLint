"""WenLint 规则定义（规则引擎 v0.1）。

Rule 结构：
    id         规则 ID（C001 套话 / H001 模糊 / E001 强调 / R001 冗余 / D001 重复 / S001 长句）
    name       英文名
    category   中文类别
    severity   warning | suggestion | error
    patterns   触发词/正则（同一规则内 OR）
    block      排除正则（命中则不报，如"由此可见一斑"）
    fixable    是否允许自动修复（高置信才 True）
    message    命中提示（{w} = 命中的词）
    profiles   适用的场景（缺省 = 全部）
"""

RULES = [
    # ---------- C: 套话 / 废话填充 ----------
    {
        "id": "C001", "name": "cliche-intro", "category": "套话/废话填充",
        "severity": "warning", "message": "套话「{w}」，删掉更直接",
        "patterns": ["总而言之", "综上所述", "值得注意的是", "众所周知",
                     "毋庸置疑", "不难发现", "需要注意的是", "换句话说"],
        "fixable": True,
    },
    {
        "id": "C002", "name": "buzzword", "category": "套话/废话填充",
        "severity": "warning", "message": "术语滥用「{w}」，换成大白话",
        "patterns": ["赋能", "抓手", "颗粒度", "底层逻辑",
                     "顶层设计", "多维度", "保驾护航"],
        # "闭环"已移除：医疗/流程领域高频正当术语（处置闭环/反馈闭环/诊后闭环），误报率 >90%
        "fixable": False,
    },
    {
        "id": "C003", "name": "cliche-由此可见", "category": "套话/废话填充",
        "severity": "warning", "message": "套话「{w}」，删掉更直接",
        "patterns": ["由此可见"],
        "block": "由此可见一斑",
        "fixable": True,
    },
    # ---------- H: 模糊词 ----------
    {
        "id": "H001", "name": "hedge-hard", "category": "模糊词",
        "severity": "warning", "message": "模糊词「{w}」，表述要精确",
        "patterns": ["大概", "好像", "似乎", "差不多"],
        "fixable": False,
    },
    {
        "id": "H002", "name": "hedge-soft", "category": "模糊词",
        "severity": "suggestion",
        "message": "模糊词「{w}」——论文/技术文档中如需保留学术审慎可忽略",
        "patterns": ["可能", "或许", "也许", "大约", "一定程度上", "某种程度"],
        "fixable": False,
        # academic/formal profile 下降级（见 profiles.py）
    },
    {
        "id": "H003", "name": "hedge-左右", "category": "模糊词",
        "severity": "suggestion", "message": "「左右」歧义：时间/数量约数 or 空间方位？",
        "patterns": ["左右"],
        "block": r"左右(两边|两侧|两翼|左右|边|侧|手|翼|前后|上下)",  # 空间/方位义不报
        "fixable": False,
    },
    # ---------- E: 空洞强调 ----------
    {
        "id": "E001", "name": "empty-emphasis", "category": "空洞强调",
        "severity": "suggestion", "message": "空洞强调「{w}」，删除或换成具体描述",
        "patterns": ["非常", "十分", "极其", "超级", "真的", "简直",
                     "绝对", "毫无疑问"],
        "fixable": False,
    },
    # ---------- R: 冗余结构 ----------
    {
        "id": "R001", "name": "redundant-verb", "category": "冗余结构",
        "severity": "suggestion",
        "message": "「{w}」冗余——动词直接说即可（进行+分析 → 分析）",
        "patterns": [r"进行(?=(分析|讨论|研究|说明|处理|调查|测试|验证))"],
        "fixable": False,
    },
    {
        "id": "R002", "name": "wordy-是否能够", "category": "冗余结构",
        "severity": "suggestion", "message": "「是否能够」→「能否」",
        "patterns": ["是否能够"],
        "fixable": True,
    },
    # ---------- D: 重复 ----------
    {
        "id": "D001", "name": "duplicate-word", "category": "重复用词",
        "severity": "warning", "message": "「{w}」连续重复",
        "patterns": [],  # 特殊规则：相邻重复，engine 单独处理
        "fixable": False,  # 语义风险（"分析分析"未必都该删），留给人工
    },
    # ---------- S: 句子结构 ----------
    {
        "id": "S001", "name": "long-sentence", "category": "超长句",
        "severity": "suggestion", "message": "句子过长（{len}字 > {max}），建议拆分",
        "max_len": 60,  # academic profile 放宽到 80
        "fixable": False,
    },
]


def by_id(rid):
    for r in RULES:
        if r["id"] == rid:
            return r
    return None


def rule_trigger(rule):
    """返回用于匹配的 (名称, 模式列表)"""
    return rule["id"], rule["patterns"]
