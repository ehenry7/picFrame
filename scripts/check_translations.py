import polib, re, os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
po = polib.pofile(str(PROJECT_DIR / 'translations' / 'he' / 'LC_MESSAGES' / 'messages.po'))
po_msgids = set(e.msgid for e in po if e.msgid)

template_strings = set()
files_to_check = []
for root, dirs, files in os.walk(PROJECT_DIR / 'templates'):
    for f in files:
        files_to_check.append(os.path.join(root, f))
files_to_check.append(PROJECT_DIR / 'app.py')
files_to_check.append(PROJECT_DIR / 'local_slideshow.py')

for fpath in files_to_check:
    try:
        with open(fpath, 'r', encoding='utf-8') as fh:
            content = fh.read()
        # Match _('...'), _("..."), {{ _('...') }}, etc.
        matches = re.findall(r'_\(\s*["\'](.+?)["\']\s*[\),]', content)
        template_strings.update(matches)
    except OSError as e:
        raise RuntimeError(f"Could not inspect {fpath}: {e}") from e

missing = template_strings - po_msgids
print(f'Total _() strings in code/templates: {len(template_strings)}')
print(f'Total msgids in .po file: {len(po_msgids)}')
print(f'Strings in code but NOT in .po file: {len(missing)}')
if missing:
    print()
    print('=== Missing strings (not in .po) ===')
    for s in sorted(missing)[:50]:
        print(f'  {s!r}')
