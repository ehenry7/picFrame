import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
with (PROJECT_DIR / 'templates' / 'configure.html.jinja').open(encoding='utf-8') as f:
    content = f.read()

# Find text between > and < that contains actual words (not variables, not _() calls)
# This is a rough heuristic
hardcoded = []
for m in re.finditer(r'>([^<{]+)<', content):
    text = m.group(1).strip()
    if not text:
        continue
    if text.startswith('{{') or text.startswith('{%'):
        continue
    if '{{ _(' in m.group(0):
        continue
    # Skip if it's inside a script tag
    if len(text) < 3:
        continue
    # Skip pure numbers, CSS, etc.
    if re.match(r'^[\d\s\.\-\(\)]+$', text):
        continue
    if re.match(r'^[a-z_\-]+$', text) and len(text) < 10:
        continue  # likely CSS class or similar
    hardcoded.append((m.start(), text))

print(f'Potential hardcoded text (not in _()): {len(hardcoded)}')
print()
for pos, text in hardcoded[:60]:
    # Show line number
    line = content[:pos].count('\n') + 1
    print(f'  L{line}: {text[:80]!r}')
