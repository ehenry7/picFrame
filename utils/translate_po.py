import sys
import time
import re
from polib import pofile
from deep_translator import GoogleTranslator

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

def protect_placeholders(text):
    """Remplace les placeholders par des balises non traduisibles."""
    placeholders = re.findall(r'%\([a-zA-Z0-9_]+\)[a-zA-Z]|%[sdif]|%%', text)
    protected_text = text
    for i, p in enumerate(placeholders):
        protected_text = protected_text.replace(p, f'<span class="notranslate">{i}</span>', 1)
    return protected_text, placeholders

def restore_placeholders(text, placeholders):
    """Restaure les placeholders originaux."""
    for i, p in enumerate(placeholders):
        text = re.sub(r'<span class="notranslate">\s*' + str(i) + r'\s*</span>', p, text, 1)
    return text

def translate_po_file(file_path, target_lang):
    """
    Traduit les entrées non traduites dans un fichier .po en utilisant Google Translate.
    """
    try:
        if target_lang == "he":
            target_lang = "iw"

        po = pofile(file_path)
        untranslated_entries = [
            entry for entry in po
            if not entry.obsolete and (
                not entry.translated()
                or (
                    entry.msgid_plural
                    and any(not translation for translation in entry.msgstr_plural.values())
                )
            )
        ]
        
        if not untranslated_entries:
            print(f"✅ Aucune nouvelle entrée à traduire dans {file_path}.")
            return True

        print(f"Trouvé {len(untranslated_entries)} entrées à traduire vers '{target_lang}'...")

        failed_entries = []
        for i, entry in enumerate(untranslated_entries):
            try:
                def translate_text(text):
                    protected_text, placeholders = protect_placeholders(text)
                    translated_text = GoogleTranslator(source='auto', target=target_lang).translate(protected_text)
                    return restore_placeholders(translated_text, placeholders)

                final_translated_text = translate_text(entry.msgid)
                if entry.msgid_plural:
                    plural_translation = translate_text(entry.msgid_plural)
                    entry.msgstr_plural = {
                        index: final_translated_text if index == 0 else plural_translation
                        for index in entry.msgstr_plural
                    }
                else:
                    entry.msgstr = final_translated_text

                if 'fuzzy' in entry.flags:
                    entry.flags.remove('fuzzy')
                print(f"  ({i+1}/{len(untranslated_entries)}) '{entry.msgid[:30]}...' -> '{final_translated_text[:30]}...'")
                time.sleep(0.5) # Délai pour respecter l'API
            except Exception as e:
                failed_entries.append(entry.msgid)
                print(f"  ❌ Impossible de traduire l'entrée : '{entry.msgid}'. Erreur : {e}")

        print(f"Sauvegarde du fichier traduit dans {file_path}...")
        po.save()
        print("✅ Traduction terminée.")
        if failed_entries:
            print(f"❌ {len(failed_entries)} entrée(s) n'ont pas été traduites.")
            return False
        return True

    except Exception as e:
        print(f"Une erreur est survenue : {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python utils/translate_po.py <chemin_vers_le_fichier_po> <code_langue_cible>")
        print("Exemple: python utils/translate_po.py translations/es/LC_MESSAGES/messages.po es")
        sys.exit(1)
        
    po_file_path = sys.argv[1]
    lang_code = sys.argv[2]
    
    if not translate_po_file(po_file_path, lang_code):
        sys.exit(1)