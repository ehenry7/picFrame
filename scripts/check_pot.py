import polib
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
po = polib.pofile(str(PROJECT_DIR / 'translations' / 'he' / 'LC_MESSAGES' / 'messages.po'))
pot = polib.pofile(str(PROJECT_DIR / 'translations' / 'messages.pot'))

po_ids = set(e.msgid for e in po if e.msgid)
pot_ids = set(e.msgid for e in pot if e.msgid)

in_pot_not_po = pot_ids - po_ids
in_po_not_pot = po_ids - pot_ids

print(f'Entries in .pot (current templates): {len(pot_ids)}')
print(f'Entries in .po (hebrew): {len(po_ids)}')
print(f'In .pot but NOT in .po (missing translations): {len(in_pot_not_po)}')
print(f'In .po but NOT in .pot (stale entries): {len(in_po_not_pot)}')

if in_pot_not_po:
    print()
    print('=== Missing from .po (will show untranslated) ===')
    for s in sorted(in_pot_not_po)[:30]:
        print(f'  {s!r}')

if in_po_not_pot:
    print()
    print('=== Stale in .po (no longer in templates) ===')
    for s in sorted(in_po_not_pot)[:20]:
        print(f'  {s!r}')
