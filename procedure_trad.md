# PictureFrame Translation Update Procedure

This document describes how to update PictureFrame's translation files using
Babel and the `deep-translator` library.

---

## 1. Prerequisites

Before you begin, make sure the following tools are installed in the global
Python installation used by PictureFrame.

### Install the required tools

From the project root, install the required libraries (included in
`requirements.txt`):

```bash
python -m pip install deep-translator polib
```

### `babel.cfg` configuration file

Make sure `babel.cfg` exists in the project root with the following content.
This file tells Babel where to find translatable text.

```ini
[python: **.py]
[jinja2: **/templates/**.jinja]
extensions=jinja2.ext.i18n
```

---

## 2. Update procedure

The process has four main steps.

### Step 1: Extract translatable text

This command scans the project's `.py` and `.html` files for text marked for
translation (for example, `_('My text')`) and creates or updates the
`messages.pot` template file.

```bash
pybabel extract -F babel.cfg -o translations/messages.pot .
```

**Note:** Do not omit the `.` at the end of the command; it tells Babel to scan
the current directory.

### Step 2: Update language files

This command compares the template (`messages.pot`) with each language's `.po`
file and adds any new strings that need translation.

```bash
pybabel update -i translations/messages.pot -d translations
```

### Step 3: Translate new strings

English is the source language. The custom script `utils/translate_po.py`
translates missing strings into French and Hebrew.

```bash
# Translate the French catalog
python utils/translate_po.py translations/fr/LC_MESSAGES/messages.po fr

# Translate the Hebrew catalog
python utils/translate_po.py translations/he/LC_MESSAGES/messages.po he
```

**Tip:** After this step, review the `.po` files in an editor such as Poedit and
correct any errors in the automatic translations.

### Step 4: Compile translations

This final command converts the human-readable `.po` files into optimized
binary `.mo` files, which the application uses to display translations.

```bash
pybabel compile -d translations
```

---

After completing these steps, restart PictureFrame to apply the updated
translations.

---

## 3. Convert this document to PDF

* **VS Code:** Install an extension such as "Markdown PDF", then right-click
  the `.md` file and export it.
* **Online:** Use a site such as md2pdf.netlify.app by copying and pasting this
  text.
* **Command line:** If `pandoc` is installed, run:
  `pandoc procedure_trad.md -o procedure_trad.pdf`.
