import polib
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
po = polib.pofile(str(PROJECT_DIR / 'translations' / 'he' / 'LC_MESSAGES' / 'messages.po'))
po_msgids = set(e.msgid for e in po if e.msgid)

english_strings = [
    'Date format reference',
    'Auto Enhance', 'Vivid', 'Warm', 'Cool', 'Dramatic B&W',
    'Soft Glow', 'Sharpen', 'Duotone', 'Posterize', 'Matte',
    'Film Grain', 'Pencil Sketch', 'Cinematic', 'Watercolor',
    'Four-digit year', 'Two-digit year', 'Month number', 'Day of month',
    'Full / abbreviated month name', 'Full / abbreviated weekday name',
    'Hour (24-hour / 12-hour)', 'Minute / second',
    'Combine these codes with spaces or punctuation.',
    'Examples (15 June 2020):',
    'Dark Edges', 'Tilt Shift', 'Cross Process',
    'Selective Color - Red', 'Selective Color - Green', 'Selective Color - Blue',
    'End zoom (1.15 = 15%% zoom):',
    'Month number',
    'No Metadata',
    'Random',
]

found = []
not_found = []
for s in english_strings:
    if s in po_msgids:
        entry = po.find(s)
        if entry and entry.translated():
            found.append(s)
        else:
            not_found.append(s + ' (in .po but NOT translated)')
    else:
        not_found.append(s + ' (NOT in .po file at all)')

print(f'English strings found and translated: {len(found)}')
print(f'English strings NOT translated: {len(not_found)}')
print()
for s in not_found:
    print(f'  {s}')
