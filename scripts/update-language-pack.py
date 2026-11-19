#!/usr/bin/env python3
"""Create or update a BIMaestro language pack (BIMaestro/Content/Languages/<code>.json).

The script collects every interface text that BIMaestro can translate:

* ``UiLanguage.T("français", "English")`` calls in the C# code (key: the English text),
* ``UiLanguage.T("français")`` calls and the built-in ``UiTextCatalog`` (key: the English
  text when the catalog has one, otherwise the French text),
* literal Text/Content/Header/ToolTip/Title attributes of the XAML windows that have no
  English entry yet (key: the French text).

Existing translations are kept, new texts are added with an empty value ("" means
"not translated yet", BIMaestro then shows the English text).

Examples
    python scripts/update-language-pack.py --code de --name Deutsch --culture de-DE --revit-language German
    python scripts/update-language-pack.py --code de            # refresh an existing pack
    python scripts/update-language-pack.py --template          # refresh _template.json
    python scripts/update-language-pack.py --code de --prune    # also drop texts no longer used
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "BIMaestro"
LANG_DIR = SOURCE_DIR / "Content" / "Languages"
CATALOG_FILE = SOURCE_DIR / "Localization" / "UiLanguage.cs"
SKIP_DIRS = {"bin", "obj", "Test"}
RESERVED_CODES = {"auto", "fr", "en"}

XAML_ATTRIBUTES = ("Text", "Content", "Header", "ToolTip", "Title")


# --------------------------------------------------------------------------- C# parsing

def _read_csharp_string(src: str, i: int):
    """Parse a C# string literal starting at src[i]. Returns (value, end) or None.

    Interpolated strings ($"...") are rejected because their runtime value changes.
    """
    verbatim = False
    if src.startswith("@\"", i):
        verbatim, i = True, i + 1
    elif src.startswith("$", i) or src.startswith("@$", i):
        return None
    if i >= len(src) or src[i] != '"':
        return None
    i += 1
    out = []
    while i < len(src):
        c = src[i]
        if verbatim:
            if c == '"':
                if src.startswith('""', i):
                    out.append('"')
                    i += 2
                    continue
                return "".join(out), i + 1
            out.append(c)
            i += 1
            continue
        if c == '"':
            return "".join(out), i + 1
        if c == "\n":
            return None
        if c == "\\":
            n = src[i + 1]
            simple = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "'": "'",
                      "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
            if n in simple:
                out.append(simple[n])
                i += 2
            elif n == "u":
                out.append(chr(int(src[i + 2:i + 6], 16)))
                i += 6
            elif n == "U":
                out.append(chr(int(src[i + 2:i + 10], 16)))
                i += 10
            elif n == "x":
                m = re.match(r"[0-9a-fA-F]{1,4}", src[i + 2:])
                out.append(chr(int(m.group(0), 16)))
                i += 2 + len(m.group(0))
            else:
                return None
            continue
        out.append(c)
        i += 1
    return None


def _skip_ws(src: str, i: int) -> int:
    while i < len(src):
        if src[i].isspace():
            i += 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = len(src) if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = len(src) if j < 0 else j + 2
        else:
            break
    return i


def _read_literal_expr(src: str, i: int):
    """A string literal, optionally concatenated: "a" + "b" + @"c"."""
    i = _skip_ws(src, i)
    first = _read_csharp_string(src, i)
    if first is None:
        return None
    value, i = first
    while True:
        j = _skip_ws(src, i)
        if j < len(src) and src[j] == "+":
            nxt = _read_csharp_string(src, _skip_ws(src, j + 1))
            if nxt is None:
                return None
            value += nxt[0]
            i = nxt[1]
        else:
            return value, j


T_CALL = re.compile(r"(?<![\w.])(?:UiLanguage\.)?T\(")


def collect_t_calls(path: Path, pairs: dict, singles: set, stats: dict):
    src = path.read_text(encoding="utf-8-sig")
    # Only consider bare T( inside UiLanguage.cs, everywhere else require UiLanguage.T(
    for m in T_CALL.finditer(src):
        if not m.group(0).startswith("UiLanguage.") and path.name != "UiLanguage.cs":
            continue
        first = _read_literal_expr(src, m.end())
        if first is None:
            stats["dynamic"] += 1
            continue
        french, i = first
        if i < len(src) and src[i] == ")":
            singles.add(french)
            continue
        if i >= len(src) or src[i] != ",":
            stats["dynamic"] += 1
            continue
        second = _read_literal_expr(src, i + 1)
        if second is None or second[1] >= len(src) or src[second[1]] != ")":
            stats["dynamic"] += 1
            continue
        english = second[0]
        pairs.setdefault(english, french)
        stats["pairs"] += 1


CATALOG_ENTRY = re.compile(r'\[\s*(@?")')


def collect_catalog(path: Path) -> dict:
    """French -> English entries of UiTextCatalog (["fr"] = "en")."""
    src = path.read_text(encoding="utf-8-sig")
    start = src.find("class UiTextCatalog")
    catalog = {}
    for m in CATALOG_ENTRY.finditer(src, start):
        key = _read_csharp_string(src, m.start(1))
        if key is None:
            continue
        french, i = key
        i = _skip_ws(src, i)
        if not src.startswith("]", i):
            continue
        i = _skip_ws(src, i + 1)
        if not src.startswith("=", i) or src.startswith("==", i):
            continue
        value = _read_literal_expr(src, i + 1)
        if value is None:
            continue
        catalog[french] = value[0]
    return catalog


# --------------------------------------------------------------------------- XAML parsing

XAML_ATTR = re.compile(r'\b(' + "|".join(XAML_ATTRIBUTES) + r')="([^"]*)"')
XML_ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'"}


def _xml_unescape(text: str) -> str:
    def repl(m):
        ent = m.group(0)
        if ent in XML_ENTITIES:
            return XML_ENTITIES[ent]
        if ent.startswith("&#x"):
            return chr(int(ent[3:-1], 16))
        if ent.startswith("&#"):
            return chr(int(ent[2:-1]))
        return ent
    return re.sub(r"&(#x[0-9a-fA-F]+|#\d+|\w+);", repl, text)


def collect_xaml(path: Path, texts: set):
    src = path.read_text(encoding="utf-8-sig")
    for m in XAML_ATTR.finditer(src):
        value = _xml_unescape(m.group(2))
        if not value.strip() or value.lstrip().startswith("{"):
            continue
        if not re.search(r"[^\W\d_]{2,}", value):  # needs at least a word
            continue
        texts.add(value)


# --------------------------------------------------------------------------- main

def iter_files(pattern: str):
    for path in sorted(SOURCE_DIR.rglob(pattern)):
        if SKIP_DIRS.intersection(path.relative_to(SOURCE_DIR).parts):
            continue
        yield path


def collect_keys():
    stats = {"pairs": 0, "dynamic": 0}
    pairs, singles, xaml = {}, set(), set()
    for path in iter_files("*.cs"):
        collect_t_calls(path, pairs, singles, stats)
    for path in iter_files("*.xaml"):
        collect_xaml(path, xaml)
    catalog = collect_catalog(CATALOG_FILE)

    keys = set(pairs)                      # English texts of T("fr", "en")
    english_of_french = dict(catalog)
    for french in singles | xaml | set(catalog):
        keys.add(english_of_french.get(french, french))
    keys.discard("")
    return keys, stats, len(catalog), len(xaml)


def write_pack(path: Path, header: dict, keys: set, prune: bool):
    existing = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        for field in ("code", "name", "culture", "revitLanguages"):
            if field in data and header.get(field) in (None, [], ""):
                header[field] = data[field]
        existing = data.get("strings", {}) or {}

    strings = {}
    for key in sorted(keys, key=lambda k: (k.casefold(), k)):
        strings[key] = existing.get(key, "")
    obsolete = {k: v for k, v in existing.items() if k not in keys}
    if not prune:
        strings.update(obsolete)

    pack = {k: v for k, v in header.items() if v not in (None, [], "")}
    pack["strings"] = strings
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    translated = sum(1 for k in keys if existing.get(k, "").strip())
    return translated, len(obsolete)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--code", help="language code, e.g. de, es, it, pt-BR")
    parser.add_argument("--name", help="name shown in BIMaestro, e.g. Deutsch")
    parser.add_argument("--culture", help=".NET culture for dates and numbers, e.g. de-DE")
    parser.add_argument("--revit-language", action="append", default=[],
                        help="Revit LanguageType selecting this pack in Automatic mode, e.g. German (repeatable)")
    parser.add_argument("--template", action="store_true", help="write Content/Languages/_template.json")
    parser.add_argument("--prune", action="store_true", help="remove texts that are no longer used")
    args = parser.parse_args(argv)

    if not args.template and not args.code:
        parser.error("use --code <code> or --template")
    if args.code and args.code.lower() in RESERVED_CODES:
        parser.error(f"'{args.code}' is built into BIMaestro and cannot be a language pack")

    keys, stats, catalog_count, xaml_count = collect_keys()

    if args.template:
        path = LANG_DIR / "_template.json"
        header = {"code": "xx", "name": "Language name", "culture": "xx-XX", "revitLanguages": ["RevitLanguageType"]}
        if path.exists():
            path.unlink()
    else:
        path = LANG_DIR / f"{args.code}.json"
        header = {"code": args.code, "name": args.name, "culture": args.culture,
                  "revitLanguages": args.revit_language}

    translated, obsolete = write_pack(path, header, keys, args.prune)

    print(f"{path.relative_to(ROOT)}")
    print(f"  texts:       {len(keys)}  (T(fr, en): {stats['pairs']}, catalog: {catalog_count}, XAML: {xaml_count})")
    print(f"  translated:  {translated}")
    print(f"  obsolete:    {obsolete}{' (removed)' if args.prune else ''}")
    print(f"  skipped T() calls with interpolated or computed text: {stats['dynamic']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
