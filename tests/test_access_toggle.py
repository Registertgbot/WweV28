from services import access


def test_approval_toggle():
    access._allowed.clear()
    access.set_required(True)
    assert not access.is_allowed(-100999)
    access.set_required(False)
    assert access.is_allowed(-100999)
    access._allowed.add(-100111)
    access.set_required(True)
    assert access.is_allowed(-100111) and not access.is_allowed(-100999)
