# Langues de l'interface / Interface languages

*Français ci-dessous.*

## English

French and English are built into BIMaestro. Every other language is a **language pack**: a JSON file
that anyone can create without changing or rebuilding the code.

### Where BIMaestro looks for packs

1. `Content\Languages\*.json` next to `BIMaestro.dll` (packs shipped with the installer).
2. `Documents\BIMaestro_Revit\SauvegardePréférence\Languages\*.json` (packs added by the user,
   no administrator rights needed). Entries here override the shipped ones.

Files whose name starts with `_` are ignored. After adding a file, restart Revit; the language then appears
in **Options BIMaestro → Language**. In *Automatic* mode a pack is chosen when Revit runs in
one of its `revitLanguages`.

### File format

```json
{
  "code": "de",
  "name": "Deutsch",
  "culture": "de-DE",
  "revitLanguages": ["German"],
  "strings": {
    "Search": "Suchen",
    "Show more": "Mehr anzeigen",
    "Rechercher par nom ou description": "Nach Name oder Beschreibung suchen"
  }
}
```

| Field | Meaning |
|---|---|
| `code` | Short identifier saved in the user preferences (`fr`, `en` and `auto` are reserved). |
| `name` | Name shown in the language list. |
| `culture` | .NET culture for dates and numbers (optional, defaults to `code`). |
| `revitLanguages` | Revit `LanguageType` names that select the pack in Automatic mode, e.g. `German`, `Spanish`, `Italian`, `Brazilian_Portuguese`. |
| `strings` | Key = the **English** text of BIMaestro (or the French text when there is no English one), value = the translation. |

An empty value means "not translated yet": BIMaestro then shows the English text, so a pack can be
completed step by step. Keep placeholders such as line breaks (`\n`), leading or trailing spaces and
punctuation, because the code sometimes joins several texts together.

### Creating or updating a pack

`_template.json` lists every text BIMaestro can translate. To start a language, or to add the texts of a new
BIMaestro version to an existing pack without losing translations:

```
python scripts/update-language-pack.py --code de --name Deutsch --culture de-DE --revit-language German
```

Texts built at run time (for example `$"{count} elements"`) cannot be matched yet and stay in English.

## Français

Le français et l'anglais sont intégrés au code. Toute autre langue est un **pack de langue** : un fichier JSON
que chacun peut créer sans modifier ni recompiler BIMaestro.

* Emplacements : `Content\Languages` à côté de `BIMaestro.dll`, puis
  `Documents\BIMaestro_Revit\SauvegardePréférence\Languages` (prioritaire).
* Dans `strings`, la clé est le texte **anglais** de BIMaestro (ou le texte français s'il n'existe pas
  en anglais) et la valeur sa traduction. Une valeur vide affiche l'anglais.
* `python scripts/update-language-pack.py --code <code>` crée le pack ou y ajoute les nouveaux textes
  en conservant les traductions existantes. `_template.json` contient la liste complète.
* Redémarrer Revit puis choisir la langue dans **Options BIMaestro → Langue**.
