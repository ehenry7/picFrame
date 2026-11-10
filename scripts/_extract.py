import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PROJECT_DIR = Path(__file__).resolve().parents[1]
with (PROJECT_DIR / 'translations' / 'he' / 'LC_MESSAGES' / 'messages.po').open(encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

entries = []
in_msgid = False
in_msgstr = False
msgid_lines = []
msgstr_lines = []
msgid_plural_lines = []
in_msgid_plural = False
msgstr_plural = {}

def join_lines(lst):
    result = ''
    for l in lst:
        l = l.strip()
        if l.startswith('"') and l.endswith('"'):
            result += l[1:-1]
    return result

for line in lines:
    stripped = line.strip()
    if stripped.startswith('#'):
        pass
    elif stripped.startswith('msgid_plural'):
        in_msgid_plural = True
        msgid_plural_lines = [stripped[len('msgid_plural '):].strip()]
    elif stripped.startswith('msgid '):
        in_msgid = True
        in_msgstr = False
        in_msgid_plural = False
        msgid_lines = [stripped[len('msgid '):].strip()]
    elif stripped.startswith('msgstr['):
        idx = stripped[len('msgstr['):].split(']')[0]
        val = stripped.split(']',1)[1].strip()
        msgstr_plural[idx] = val
    elif stripped.startswith('msgstr '):
        in_msgid = False
        in_msgstr = True
        msgstr_lines = [stripped[len('msgstr '):].strip()]
    elif stripped.startswith('"') and stripped.endswith('"'):
        if in_msgid and not in_msgid_plural:
            msgid_lines.append(stripped)
        elif in_msgid_plural:
            msgid_plural_lines.append(stripped)
        elif in_msgstr:
            msgstr_lines.append(stripped)
    elif stripped == '':
        if msgid_lines or msgstr_lines or msgstr_plural:
            mid = join_lines(msgid_lines)
            mstr = join_lines(msgstr_lines)
            entries.append({
                'msgid': mid,
                'msgstr': mstr,
                'msgid_plural': join_lines(msgid_plural_lines) if msgid_plural_lines else None,
                'msgstr_plural': dict(msgstr_plural),
            })
        msgid_lines = []
        msgstr_lines = []
        msgid_plural_lines = []
        msgstr_plural = {}
        in_msgid = False
        in_msgstr = False
        in_msgid_plural = False

if msgid_lines or msgstr_lines or msgstr_plural:
    mid = join_lines(msgid_lines)
    mstr = join_lines(msgstr_lines)
    entries.append({
        'msgid': mid,
        'msgstr': mstr,
        'msgid_plural': join_lines(msgid_plural_lines) if msgid_plural_lines else None,
        'msgstr_plural': dict(msgstr_plural),
    })

untranslated = [e for e in entries if e['msgstr'] == '' and not e['msgstr_plural']]
plural_untrans = [e for e in entries if e['msgstr_plural'] and all(v.strip('"') == '' for v in e['msgstr_plural'].values())]

result = {'simple': [e['msgid'] for e in untranslated], 'plural': [{'msgid': e['msgid'], 'msgid_plural': e['msgid_plural']} for e in plural_untrans]}
with Path(__file__).with_name('_untranslated.json').open('w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f'Total: {len(entries)}, Simple: {len(untranslated)}, Plural: {len(plural_untrans)}')
