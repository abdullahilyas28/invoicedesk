from invoicedesk.abn import format_abn, is_valid_abn


def test_ato_example_abn_is_valid():
    assert is_valid_abn("51 824 753 556")


def test_one_digit_change_is_invalid():
    assert not is_valid_abn("51 824 753 557")


def test_wrong_length_and_junk_are_invalid():
    assert not is_valid_abn("1234")
    assert not is_valid_abn("N/A")


def test_format_abn():
    assert format_abn("51824753556") == "51 824 753 556"