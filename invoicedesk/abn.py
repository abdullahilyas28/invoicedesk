"""Australian Business Number checksum (ATO algorithm)."""

ABN_WEIGHTS = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]


def is_valid_abn(abn: str) -> bool:
    """
    Subtract 1 from the first digit, weight each digit, and the sum must divide by 89.
    """
    cleaned_abn = abn.replace(" ", "")
    if len(cleaned_abn) != 11 or not cleaned_abn.isdigit():
        return False
    digits = [int(character) for character in cleaned_abn]
    digits[0] -= 1
    weighted_sum = sum(digit * weight for digit, weight in zip(digits, ABN_WEIGHTS))
    return weighted_sum % 89 == 0


def format_abn(abn: str) -> str:
    """
    '51824753556' -> '51 824 753 556', the way ABNs are printed on invoices.
    """
    return f"{abn[:2]} {abn[2:5]} {abn[5:8]} {abn[8:]}"