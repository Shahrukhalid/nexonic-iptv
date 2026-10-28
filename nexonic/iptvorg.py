"""Parsing and vocabulary shared by the official-tier discovery script and the community tier.

Holds the iptv-org specific tables (ISO 639-2/3 to 639-1 languages, category mapping, sanctions and exclusion terms)
and the reader of iptv-org style M3U files. Both ``scripts/expand_catalog.py`` and ``nexonic/community.py`` use these
definitions so a rule changed here applies to every tier.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

ISO3_TO_1 = {
    "ara": "ar",
    "ben": "bn",
    "dan": "da",
    "deu": "de",
    "ell": "el",
    "eng": "en",
    "spa": "es",
    "fas": "fa",
    "fin": "fi",
    "fra": "fr",
    "hin": "hi",
    "hun": "hu",
    "ind": "id",
    "ita": "it",
    "jpn": "ja",
    "kor": "ko",
    "kur": "ku",
    "msa": "ms",
    "zsm": "ms",
    "nld": "nl",
    "nor": "no",
    "nob": "no",
    "nno": "no",
    "pol": "pl",
    "por": "pt",
    "rus": "ru",
    "swe": "sv",
    "swa": "sw",
    "tam": "ta",
    "tha": "th",
    "tur": "tr",
    "ukr": "uk",
    "urd": "ur",
    "vie": "vi",
    "zho": "zh",
    "cmn": "zh",
    "yue": "zh",
    "ces": "cs",
    "slk": "sk",
    "slv": "sl",
    "hrv": "hr",
    "srp": "sr",
    "bos": "bs",
    "bul": "bg",
    "ron": "ro",
    "mkd": "mk",
    "sqi": "sq",
    "lit": "lt",
    "lav": "lv",
    "est": "et",
    "isl": "is",
    "cat": "ca",
    "eus": "eu",
    "glg": "gl",
    "gle": "ga",
    "cym": "cy",
    "heb": "he",
    "hye": "hy",
    "kat": "ka",
    "aze": "az",
    "kaz": "kk",
    "uzb": "uz",
    "mon": "mn",
    "pus": "ps",
    "prs": "fa",
    "tgl": "tl",
    "fil": "tl",
    "mal": "ml",
    "tel": "te",
    "kan": "kn",
    "mar": "mr",
    "guj": "gu",
    "pan": "pa",
    "ori": "or",
    "asm": "as",
    "nep": "ne",
    "sin": "si",
    "mya": "my",
    "khm": "km",
    "lao": "lo",
    "amh": "am",
    "som": "so",
    "hau": "ha",
    "yor": "yo",
    "ibo": "ig",
    "zul": "zu",
    "afr": "af",
    "mlt": "mt",
    "ltz": "lb",
    "fao": "fo",
    "kal": "kl",
    "bel": "be",
    "tat": "tt",
    "kir": "ky",
    "tuk": "tk",
    "tgk": "tg",
    "hat": "ht",
    "que": "qu",
    "grn": "gn",
    "aym": "ay",
    "mri": "mi",
    "smo": "sm",
    "ton": "to",
    "fij": "fj",
    "kin": "rw",
    "lug": "lg",
    "wol": "wo",
    "lin": "ln",
    "fry": "fy",
    "bre": "br",
    "cos": "co",
    "roh": "rm",
}
CATEGORY_MAP = {
    "auto": "lifestyle",
    "animation": "kids",
    "business": "business",
    "classic": "entertainment",
    "comedy": "entertainment",
    "cooking": "lifestyle",
    "culture": "culture",
    "documentary": "documentary",
    "education": "education",
    "entertainment": "entertainment",
    "family": "entertainment",
    "general": "general",
    "kids": "kids",
    "legislative": "legislative",
    "lifestyle": "lifestyle",
    "movies": "movies",
    "music": "music",
    "news": "news",
    "outdoor": "lifestyle",
    "public": "general",
    "relax": "lifestyle",
    "science": "science",
    "series": "series",
    "sports": "sports",
    "travel": "lifestyle",
    "weather": "weather",
}
EXCLUDED_CATEGORIES = {"xxx", "shop", "religious", "interactive"}
# Per-stream playlist options that mean the stream needs headers or DRM keys (third-party lists carry these).
SPECIAL_OPTION_PREFIXES = ("#EXTVLCOPT", "#EXTHTTP", "#KODIPROP")
# Broadcasters subject to EU/UK/US broadcasting or entity sanctions, outlets of occupation authorities, and
# countries under comprehensive sanctions. Excluded from automated admission (a maintainer must decide manually).
SANCTIONED_OWNER_TERMS = (
    "vgtrk",
    "gazprom media",
    "russian ministry of defen",
    "tv-novosti",
    "rt (",
    "sputnik",
    "islamic republic of iran broadcasting",
    "irib",
    "gtrk lnr",
    "national media group",
)
SANCTIONED_NAME_TERMS = (
    "russia today",
    "rt news",
    "rt arabic",
    "rt documentary",
    "rt espanol",
    "sputnik",
    "press tv",
    "al alam",
    "zvezda",
    "solovyov",
    "ntv",
    "rossiya",
    "russia-1",
    "russia-24",
    "russia-k",
    "pervyi kanal",
    "channel one russia",
    "perviy krymskiy",
    "lugansk 24",
    "donetsk",
    "krym 24",
    "izvestia",
    "ren tv",
)
SANCTIONED_COUNTRIES = {"kp", "sy"}
# Religious networks not tagged as such in the database.
EXCLUDED_NAME_TERMS = ("scientology", "supreme master", "cine dios", "prarthana", "ganj e hozour")
# Subscription / pay services whose streams can sit on the broadcaster's own domain without being offered free.
PAID_HOST_PATTERNS = re.compile(r"(antenaplay\.ro|telewebion\.ir)$", re.I)
PAID_NAME_TERMS = ("fox news channel", "fox business", "formula 1", "f1 ")


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:56] or "channel"


EXTINF_ATTR = re.compile(r'([a-zA-Z-]+)="([^"]*)"')


def parse_streams(path: Path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            attrs = dict(EXTINF_ATTR.findall(line))
            title = line.rsplit(",", 1)[-1].strip() if "," in line else ""
            j, opts = i + 1, []
            while j < len(lines) and lines[j].startswith("#"):
                opts.append(lines[j])
                j += 1
            if j < len(lines):
                yield attrs, title, lines[j].strip(), opts
            i = j + 1
        else:
            i += 1


def resolution_rank(title: str) -> int:
    m = re.search(r"\((\d{3,4})[pi]\)", title)
    return int(m.group(1)) if m else 0
