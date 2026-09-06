"""Profile 定义：不同文体对规则的启用/级别调整。

用法：
    academic  -> 论文（H002 学术审慎词关闭，S001 放宽到 80）
    product   -> PRD/产品文档（默认全开）
    formal    -> 对外正式文档/给医生材料（C002 升 error）
    general   -> 默认（全部规则原级别）
"""

PROFILES = {
    # 文档类（PRD/论文/报告）：叙述句可以长一些，80 字
    "general": {"disable": [], "severity_override": {},
                "params": {"S001": {"max_len": 80}}},
    "academic": {"disable": ["H002"], "severity_override": {},
                 "params": {"S001": {"max_len": 80}}},
    "product": {"disable": [], "severity_override": {},
                "params": {"S001": {"max_len": 80}}},
    "formal": {"disable": [], "severity_override": {
        "H001": "warning", "E001": "warning", "C002": "error",
    }, "params": {"S001": {"max_len": 80}}},
    # SKILL.md 指令文档：简单指令应该短句，50 字——长句说明已违反"指令要直接"
    "instruction": {"disable": [], "severity_override": {},
                    "params": {"S001": {"max_len": 50}}},
}
