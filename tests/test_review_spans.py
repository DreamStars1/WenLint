from dataclasses import replace

import pytest

from wenlint.agent import AgentProtocolError, ReviewDecision, _derive_revision


def test_trusted_unicode_span_changes_only_the_selected_repetition():
    source = "😀需要验证。第二处需要验证。"
    before = "需要验证"
    start = source.rindex(before)
    decision = ReviewDecision(1, "R001", "REWRITE", "简化", before, "应验证", "static", (), start)
    assert _derive_revision(source, [decision]) == "😀需要验证。第二处应验证。"
    with pytest.raises(AgentProtocolError, match="原文位置已失效"):
        _derive_revision(source, [replace(decision, source_start=start + 1)])
