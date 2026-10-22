"""Personal data the candidate volunteers: flagged for the recruiter, never used for scoring."""

import re

PII_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "phone": re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"),
    "aadhaar": re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"),
    "pan": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "ifsc": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),
    "card_or_account": re.compile(r"(?<!\d)\d{13,18}(?!\d)"),
    "salary": re.compile(r"(?:₹\s?\d|\brs\.?\s?\d|\binr\b|\blpa\b|\bctc\b|\bsalary\b|\blakhs?\b|\bper annum\b)", re.I),
}


def find_pii(text: str) -> list[tuple[str, str]]:
    hits = []
    for subtype, pattern in PII_PATTERNS.items():
        for m in pattern.finditer(text):
            hits.append((subtype, m.group(0)))
    return hits
