import re
import unicodedata


def slugify(name: str, fallback: str = "item") -> str:
    slug = name.translate(str.maketrans("đĐ", "dD"))
    slug = unicodedata.normalize("NFD", slug)
    slug = "".join(c for c in slug if unicodedata.category(c) != "Mn")
    slug = slug.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")[:100] or fallback
