import polib, re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
po = polib.pofile(str(PROJECT_DIR / 'translations' / 'he' / 'LC_MESSAGES' / 'messages.po'))
ph = re.compile(r'%\([a-zA-Z0-9_]+\)s|%\([a-zA-Z0-9_]+\)d|%s|%d|%%')

print('=== Verification Report ===')
print(f'Total entries: {len(po)}')
print(f'Translated: {sum(1 for e in po if e.translated())}')
print()

# 1. Singular placeholder mismatches
sing_issues = 0
for e in po:
    if not e.translated() or not e.msgstr:
        continue
    if set(ph.findall(e.msgid)) != set(ph.findall(e.msgstr)):
        sing_issues += 1
        print(f'SINGULAR MISMATCH: {e.msgid[:60]!r}')
        print(f'  src: {set(ph.findall(e.msgid))}')
        print(f'  heb: {set(ph.findall(e.msgstr))}')
print(f'Singular placeholder mismatches: {sing_issues}')
print()

# 2. Plural placeholder mismatches
pl_issues = 0
for e in po:
    if not e.msgid_plural or not e.translated():
        continue
    src_ph = set(ph.findall(e.msgid_plural))
    for idx, ms in e.msgstr_plural.items():
        if set(ph.findall(ms)) != src_ph:
            pl_issues += 1
            print(f'PLURAL[{idx}] MISMATCH: {e.msgid_plural[:60]!r}')
            print(f'  src: {src_ph}')
            print(f'  heb: {set(ph.findall(ms))}')
print(f'Plural placeholder mismatches: {pl_issues}')
print()

# 3. Newline mismatches
nl_issues = 0
for e in po:
    if not e.translated() or not e.msgstr:
        continue
    if '\n' in e.msgid and '\n' not in e.msgstr:
        nl_issues += 1
        print(f'NEWLINE MISSING: {e.msgid[:60]!r}')
print(f'Newline mismatches: {nl_issues}')
print()

# 4. Reverse newline (extra newlines in Hebrew)
rev_nl = 0
for e in po:
    if not e.translated() or not e.msgstr:
        continue
    if '\n' not in e.msgid and '\n' in e.msgstr:
        rev_nl += 1
        print(f'EXTRA NEWLINE: {e.msgid[:60]!r}')
print(f'Reverse newline issues: {rev_nl}')
print()

# 5. Show samples with %(name)s
print('=== Samples with %(name)s ===')
c = 0
for e in po:
    if e.translated() and e.msgstr and '%(name)s' in e.msgid and c < 3:
        print(f'  {e.msgid[:55]!r}')
        print(f'    -> {e.msgstr[:55]!r}')
        c += 1
print()

# 6. Show samples with newlines
print('=== Samples with newlines ===')
c = 0
for e in po:
    if e.translated() and e.msgstr and '\n' in e.msgid and c < 3:
        print(f'  {e.msgid[:55]!r}')
        print(f'    -> {e.msgstr[:55]!r}')
        c += 1

print()
print('=== Summary ===')
print(f'  Singular placeholder mismatches: {sing_issues}')
print(f'  Plural placeholder mismatches: {pl_issues}')
print(f'  Newline mismatches: {nl_issues}')
print(f'  Reverse newline issues: {rev_nl}')
print(f'  Total issues: {sing_issues + pl_issues + nl_issues + rev_nl}')
