import re

def extract_card_number(text: str) -> str | None:
    """
    Extracts a 14 or 15 digit card number from the text, matching PHP implementation.
    """
    if not text:
        return None

    # 1. Direct match for 14-15 digits
    match = re.search(r'\b(\d{14,15})\b', text)
    if match:
        return match.group(1)

    # 2. "الرقم السري" logic
    # PHP: str_replace('الرقم الساري', 'الرقم السري', $text)
    text = text.replace('الرقم الساري', 'الرقم السري')

    if 'الرقم السري' in text:
        # PHP: $ex = explode('الرقم السري', $rp);
        parts = text.split('الرقم السري')
        if len(parts) > 1:
            # PHP: $ex1 = explode("\n", trim($ex[1]));
            # PHP: if (isset($ex1[1])) ... match on $ex1[1]

            # Note: PHP ex1[1] implies the line *after* the line containing "الرقم السري" (if split by newline)
            # OR if "الرقم السري" is followed by newline immediately.
            # Let's mimic PHP logic: trim the part after "الرقم السري", then split by newline.
            after_keyword = parts[1].strip()
            lines = after_keyword.split('\n')

            if len(lines) > 1:
                # The logic checks the *second* line (index 1)
                potential_line = lines[1]
                match = re.search(r'\b(\d{14,15})\b', potential_line)
                if match:
                    return match.group(1)

    return None
