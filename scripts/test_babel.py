from flask_babel import Babel, _
from flask import Flask, session
from pathlib import Path

app = Flask(__name__)
app.config['BABEL_TRANSLATION_DIRECTORIES'] = str(Path(__file__).resolve().parents[1] / 'translations')
app.secret_key = 'test'
app.config['BABEL_DEFAULT_LOCALE'] = 'fr'
app.config['LANGUAGES'] = {'fr': 'Francais', 'en': 'English', 'he': 'Hebrew'}
babel = Babel(app, locale_selector=lambda: 'he')

with app.test_request_context('/?lang=he'):
    session['lang'] = 'he'

    tests = [
        'Configuration',
        'Diaporama',
        'Se déconnecter',
        'Sources',
        'Actions',
        'Maintenance',
        'Logs',
        'Favoris',
        'Affichage',
    ]

    for t in tests:
        result = _(t)
        translated = result != t
        print(f'  {"OK" if translated else "MISS"} {t!r} -> {result!r}')
