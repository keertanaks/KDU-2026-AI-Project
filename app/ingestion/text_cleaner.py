import re


class TextCleaner:
    """Normalize raw OCR/extraction output."""

    @staticmethod
    def clean(text: str) -> str:
        """
        1. Collapse excessive whitespace and blank lines
        2. Remove non-printable characters
        3. Normalize unicode dashes/quotes
        4. Strip leading/trailing whitespace
        """
        # Remove non-printable characters (keep newlines/tabs)
        text = re.sub(r"[^\x09\x0A\x0D\x20-\x7E -￿]", "", text)

        # Normalize unicode dashes and quotes
        text = text.replace("–", "-").replace("—", "-")
        text = text.replace("‘", "'").replace("’", "'")
        text = text.replace("“", '"').replace("”", '"')

        # Collapse 3+ consecutive newlines to double newline
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Collapse multiple spaces on a single line
        text = re.sub(r"[ \t]{2,}", " ", text)

        return text.strip()
