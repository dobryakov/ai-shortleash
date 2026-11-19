"""URL slug helper — incomplete on purpose for Shortleash experiments."""


def slugify(text: str) -> str:
    import re

    # Normalize the text to lowercase
    text = text.lower()

    # Replace runs of whitespace and punctuation with a single hyphen
    text = re.sub(r'[^a-z0-9]+', '-', text)

    # Strip leading and trailing hyphens
    return text.strip('-').lower()
