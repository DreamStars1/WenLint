"""Profile 定义：不同文体对规则的启用/级别调整。

用法：
    academic  -> 论文（H002 学术审慎词关闭，S001 放宽到 80）
    product   -> PRD/产品文档（默认全开）
    formal    -> 对外正式文档/给医生材料（C002 升 error）
    general   -> 默认（全部规则原级别）
"""

PROFILES = {
    "general": {"disable": [], "severity_override": {}, "params": {}},
    "academic": {"disable": ["H002"], "severity_override": {},
                 "params": {"S001": {"max_len": 80}}},
    "product": {"disable": [], "severity_override": {},
                "params": {"S001": {"max_len": 60}}},
    "formal": {"disable": [], "severity_override": {
        "H001": "warning", "E001": "warning", "C002": "error",
    }, "params": {"S001": {"max_len": 60}}},
    # 指令/技术文档（SKILL.md、README、操作手册）：句子常含命令/路径/术语，
    # 60 字阈值不适用；结构问题（主文件过大）由 A900 文件级规则负责
    "instruction": {"disable": [], "severity_override": {},
                    "params": {"S001": {"max_len": 110}}},
}
