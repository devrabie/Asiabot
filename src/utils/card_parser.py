import re

ARABIC_TO_ASCII = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')

def normalize_text(text: str) -> str:
    """Converts Eastern Arabic and Perso-Arabic digits to ASCII digits."""
    if not text:
        return ""
    return text.translate(ARABIC_TO_ASCII)

def extract_card_number(text: str) -> str | None:
    """
    Extracts a 14 or 15 digit card number from the text.
    Handles consecutive digits, formatted digit groups (with spaces, dashes, dots),
    Eastern Arabic numerals, and keyword-anchored numbers.
    """
    if not text:
        return None

    text = normalize_text(text)
    text_replaced = text.replace('الرقم الساري', 'الرقم السري')

    # 1. Keyword-based search ("الرقم السري", "رمز التعبئة", "كود التعبئة", "PIN", "Voucher", etc.)
    keywords = ['الرقم السري', 'رمز التعبئة', 'كود التعبئة', 'رقم الكارت', 'رقم التعبئة', 'PIN', 'Code', 'Voucher']
    for kw in keywords:
        if kw.lower() in text_replaced.lower():
            idx = text_replaced.lower().find(kw.lower())
            after = text_replaced[idx + len(kw):]
            for line in after.split('\n'):
                # Check for direct 14-15 digits
                match = re.search(r'\b(\d{14,15})\b', line)
                if match:
                    return match.group(1)
                # Check formatted digits on this line (e.g. 1234 5678 9012 345)
                formatted = re.findall(r'(?:\b\d{1,6}[\s\-\.\/]+){2,8}\d{1,6}\b', line)
                for cand in formatted:
                    digits_only = re.sub(r'\D', '', cand)
                    if len(digits_only) in (14, 15):
                        return digits_only
                # Check total digits in line
                digits_in_line = re.sub(r'\D', '', line)
                if len(digits_in_line) in (14, 15):
                    return digits_in_line

    # 2. Direct match for 14-15 consecutive digits
    match = re.search(r'\b(\d{14,15})\b', text)
    if match:
        return match.group(1)

    # 3. Match 14-15 digits formatted with spaces, dashes, dots, or slashes
    pattern = r'(?:\b\d{1,6}[\s\-\.\/]+){2,8}\d{1,6}\b'
    for candidate in re.findall(pattern, text):
        digits_only = re.sub(r'\D', '', candidate)
        if len(digits_only) in (14, 15):
            return digits_only

    # 4. Fallback: If all digits in the text form exactly 14 or 15 digits
    all_digits = re.sub(r'\D', '', text)
    if len(all_digits) in (14, 15):
        return all_digits

    return None
