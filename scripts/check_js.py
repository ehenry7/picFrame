import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
with (PROJECT_DIR / 'templates' / 'configure.html.jinja').open(encoding='utf-8') as f:
    content = f.read()

# Find all text inside <script> tags
script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
print(f'Script blocks found: {len(script_blocks)}')
print(f'Total script content chars: {sum(len(s) for s in script_blocks)}')

# Find French-looking strings in JavaScript
french_in_js = set()
for block in script_blocks:
    # Find strings with accented French characters
    matches = re.findall(r'["\']([^"\']*[\xc3\x89\xc3\x80\xc3\xa9\xc3\xa8\xc3\xaa\xc3\xab\xc3\xa0\xc3\xa2\xc3\xa7\xc3\xae\xc3\xaf\xc3\xb4\xc3\xbb\xc3\xb9\xc3\xbc][^"\']*)["\']', block)
    french_in_js.update(matches)

    # Find common French UI words in JS strings
    french_words = ['Erreur', 'Chargement', 'Veuillez', 'Aucun', 'photo', 'diaporama',
                    'Configuration', 'Supprimer', 'Créer', 'Modifier', 'playlist',
                    'invitation', 'mise à jour', 'redémarrage', 'connexion',
                    'mot de passe', 'sauvegarde', 'restauration', 'import',
                    'préparation', 'valider', 'rejeter', 'approuver', 'Lancement',
                    'Démarrage', 'Arrêter', 'Activer', 'Désactiver', 'Actualiser',
                    'Enregistrer', 'Tester', 'Importer', 'Envoyer', 'Télécharger',
                    'Réseau', 'sécurité', 'Système', 'Application']
    for word in french_words:
        pattern = r'["\']([^"\']*' + re.escape(word) + r'[^"\']*)["\']'
        matches = re.findall(pattern, block, re.IGNORECASE)
        french_in_js.update(matches)

# Also check for {{ _('...') }} calls INSIDE script blocks (these ARE translated)
translated_in_js = set()
for block in script_blocks:
    matches = re.findall(r"_\(\s*['\"](.+?)['\"]\s*\)", block)
    translated_in_js.update(matches)

print(f'French strings hardcoded in JavaScript (NOT translated): {len(french_in_js)}')
print(f'Strings using _() in JavaScript (translated): {len(translated_in_js)}')
print()
print('=== Hardcoded French strings in JS (first 50) ===')
for s in sorted(french_in_js)[:50]:
    print(f'  {s!r}')
