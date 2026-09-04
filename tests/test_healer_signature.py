"""healer/signature 单元测试：签名稳定性与区分度。"""

from __future__ import annotations

from aiae.healer.signature import make_signature, structure_fingerprint


def _base_elements():
    return [
        {"tag": "input", "name": "username", "type": "text"},
        {"tag": "input", "name": "password", "type": "password"},
        {"tag": "button", "text": "Login"},
    ]


def test_same_input_same_signature():
    s1 = make_signature(error_type="locator_not_found", locator="input[name=username]",
                        page_title="TodoAPP", elements=_base_elements())
    s2 = make_signature(error_type="locator_not_found", locator="input[name=username]",
                        page_title="TodoAPP", elements=_base_elements())
    assert s1 == s2


def test_different_locator_different_signature():
    a = make_signature(error_type="locator_not_found", locator="input[name=username]",
                       page_title="TodoAPP", elements=_base_elements())
    b = make_signature(error_type="locator_not_found", locator="input[name=user_name]",
                       page_title="TodoAPP", elements=_base_elements())
    assert a != b


def test_different_page_different_signature():
    a = make_signature(error_type="locator_not_found", locator="input[name=username]",
                       page_title="TodoAPP", elements=_base_elements())
    b = make_signature(error_type="locator_not_found", locator="input[name=username]",
                       page_title="OtherPage", elements=_base_elements())
    assert a != b


def test_element_order_does_not_change_fingerprint():
    els = _base_elements()
    rev = list(reversed(els))
    assert structure_fingerprint(els) == structure_fingerprint(rev)  # 顺序抖动不影响命中


def test_fingerprint_changes_when_structure_changes():
    before = _base_elements()
    after = [{"tag": "input", "name": "user_name", "type": "text"},
             {"tag": "input", "name": "password", "type": "password"},
             {"tag": "button", "text": "Login"}]
    assert structure_fingerprint(before) != structure_fingerprint(after)  # name 改了 -> 指纹变
