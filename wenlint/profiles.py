"""Profile 定义：不同文体对规则的启用/级别调整。

用法：
    academic  -> 论文（H002 学术审慎词关闭，S001 放宽到 80）
    product   -> PRD/产品文档（启用 DOC002 标题编号断层检查）
    formal    -> 对外正式文档/给医生材料（H001/E001 升 warning）
    general   -> 默认（全部规则原级别；DOC002 关闭）
"""

PROFILES = {
    # 文档类（PRD/论文/报告）：叙述句可以长一些，80 字
    "general": {"disable": ["DOC002"], "severity_override": {},
                "params": {"S001": {"max_len": 80}}},
    "academic": {"disable": ["H002", "DOC002"], "severity_override": {},
                 "params": {"S001": {"max_len": 80}}},
    # product：相对 general 明确启用标题编号结构策略（DOC002）
    "product": {"disable": [], "severity_override": {},
                "params": {"S001": {"max_len": 80}}},
    "formal": {"disable": ["DOC002"], "severity_override": {
        "H001": "warning", "E001": "warning",
    }, "params": {"S001": {"max_len": 80}}},
    # SKILL.md 指令文档：简单指令应该短句，50 字——长句说明已违反"指令要直接"
    "instruction": {"disable": ["DOC002"], "severity_override": {},
                    "params": {"S001": {"max_len": 50}}},
}
