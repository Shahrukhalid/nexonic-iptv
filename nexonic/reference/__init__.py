"""Reference tables: countries, languages and categories."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_COUNTRY_COLUMNS = ("code", "name", "flag")


class ReferenceDataError(RuntimeError):
    """The bundled reference data is missing or malformed (a packaging or editing error, never user input)."""


def load_countries(path: Path) -> dict[str, dict[str, str]]:
    """Read a countries CSV. Fails loudly: a silently empty or partial table would mislabel every playlist."""
    out: dict[str, dict[str, str]] = {}
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in _COUNTRY_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise ReferenceDataError(f"{path.name}: missing column(s) {', '.join(missing)}")
            for n, row in enumerate(reader, start=2):
                code, name = (row.get("code") or "").strip(), (row.get("name") or "").strip()
                if not code or not name:
                    raise ReferenceDataError(f"{path.name} line {n}: empty code or name")
                out[code.lower()] = {"name": name, "flag": (row.get("flag") or "").strip()}
    except FileNotFoundError as exc:
        raise ReferenceDataError(f"reference data file not found: {path}") from exc
    if not out:
        raise ReferenceDataError(f"{path.name}: no country rows (truncated file?)")
    return out


@lru_cache(maxsize=1)
def countries() -> dict[str, dict[str, str]]:
    """ISO 3166-1 alpha-2 code (lowercase) -> {name, flag}.

    Data: iptv-org/database data/countries.csv (public domain).
    """
    return load_countries(_HERE / "countries.csv")


# ISO 639-1 codes Nexonic supports. Extend this table when a new language is added.
LANGUAGES: dict[str, str] = {
    "af": "Afrikaans",
    "am": "Amharic",
    "ar": "Arabic",
    "as": "Assamese",
    "ay": "Aymara",
    "az": "Azerbaijani",
    "be": "Belarusian",
    "bg": "Bulgarian",
    "bn": "Bengali",
    "br": "Breton",
    "bs": "Bosnian",
    "ca": "Catalan",
    "co": "Corsican",
    "cs": "Czech",
    "cy": "Welsh",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "eu": "Basque",
    "fa": "Persian",
    "fi": "Finnish",
    "fj": "Fijian",
    "fo": "Faroese",
    "fr": "French",
    "fy": "Western Frisian",
    "ga": "Irish",
    "gl": "Galician",
    "gn": "Guarani",
    "gu": "Gujarati",
    "ha": "Hausa",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "ht": "Haitian Creole",
    "hu": "Hungarian",
    "hy": "Armenian",
    "id": "Indonesian",
    "ig": "Igbo",
    "is": "Icelandic",
    "it": "Italian",
    "ja": "Japanese",
    "ka": "Georgian",
    "kk": "Kazakh",
    "kl": "Greenlandic",
    "km": "Khmer",
    "kn": "Kannada",
    "ko": "Korean",
    "ku": "Kurdish",
    "ky": "Kyrgyz",
    "lb": "Luxembourgish",
    "lg": "Ganda",
    "ln": "Lingala",
    "lo": "Lao",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mi": "Maori",
    "mk": "Macedonian",
    "ml": "Malayalam",
    "mn": "Mongolian",
    "mr": "Marathi",
    "ms": "Malay",
    "mt": "Maltese",
    "my": "Burmese",
    "ne": "Nepali",
    "nl": "Dutch",
    "no": "Norwegian",
    "or": "Odia",
    "pa": "Punjabi",
    "pl": "Polish",
    "ps": "Pashto",
    "pt": "Portuguese",
    "qu": "Quechua",
    "rm": "Romansh",
    "ro": "Romanian",
    "ru": "Russian",
    "rw": "Kinyarwanda",
    "si": "Sinhala",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sm": "Samoan",
    "so": "Somali",
    "sq": "Albanian",
    "sr": "Serbian",
    "sv": "Swedish",
    "sw": "Swahili",
    "ta": "Tamil",
    "te": "Telugu",
    "tg": "Tajik",
    "th": "Thai",
    "tk": "Turkmen",
    "tl": "Tagalog",
    "to": "Tongan",
    "tr": "Turkish",
    "tt": "Tatar",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "uz": "Uzbek",
    "vi": "Vietnamese",
    "wo": "Wolof",
    "yo": "Yoruba",
    "zh": "Chinese",
    "zu": "Zulu",
}

# Category id -> display name. Adult categories are intentionally absent: they cannot be expressed in the schema.
CATEGORIES: dict[str, str] = {
    "business": "Business",
    "culture": "Culture",
    "documentary": "Documentary",
    "education": "Education",
    "entertainment": "Entertainment",
    "general": "General",
    "kids": "Kids",
    "legislative": "Legislative",
    "lifestyle": "Lifestyle",
    "movies": "Movies",
    "music": "Music",
    "news": "News",
    "science": "Science",
    "series": "Series",
    "sports": "Sports",
    "weather": "Weather",
}
