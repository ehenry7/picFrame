#!/bin/bash

# Ce script est le point d'entrée principal de PictureFrame, géré par Sway.
# Il assure qu'une seule instance de l'application est en cours et gère les redémarrages.

# Code de sortie spécial pour demander un redémarrage
RESTART_CODE=42

cd "$(dirname "$0")" || exit 1
mkdir -p logs || exit 1

# Empêcher les instances multiples
LOCK_FILE="/tmp/pictureframe_app.lock"
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if ps -p "$PID" > /dev/null; then
        echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 ❌ Instance déjà en cours (PID: $PID). Abandon." >> logs/pictureframe.log
        exit 1
    fi
fi
echo $$ > "$LOCK_FILE"

# Se placer dans le répertoire du script pour que les chemins relatifs fonctionnent
cd "$(dirname "$0")" || exit 1

# S'assurer que le dossier de logs existe
mkdir -p logs

cleanup() {
    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🧹 Nettoyage des processus PictureFrame existants..." >> logs/pictureframe.log
    # Tuer le processus du diaporama s'il est en cours
    if [ -f /tmp/pictureframe_slideshow.pid ]; then
        pkill -F /tmp/pictureframe_slideshow.pid 2>/dev/null || true
        rm -f /tmp/pictureframe_slideshow.pid
    fi
    # Tuer toute instance précédente de l'application Flask (app.py)
    # Utilisation de pkill -f pour plus de robustesse
    pkill -f "python3 -u app.py" 2>/dev/null || true
    pkill -f "python3 app.py" 2>/dev/null || true
    pkill -f ffmpeg 2>/dev/null || true
    sleep 1 # Laisser le temps aux processus de se terminer
}

while true; do
    # Nettoyer avant chaque lancement
    cleanup

		echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 ================================================================" >> logs/pictureframe.log
		echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🚀 Lancement de l'application PictureFrame... 🚀🚀🚀🚀🚀🚀🚀🚀🚀" >> logs/pictureframe.log
		echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 ================================================================" >> logs/pictureframe.log
    
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    fi

    # Lancer l'application 
    python3 -u app.py >> logs/pictureframe.log 2>&1

    exit_code=$?
    echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🛑 Application terminée avec code $exit_code" >> logs/pictureframe.log

    if [ $exit_code -eq 0 ]; then
        echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 ✅ Arrêt normal (Code 0)" >> logs/pictureframe.log
        break
    fi

    if [ $exit_code -ne $RESTART_CODE ]; then
        echo "📟📟$(date +'%d-%m %H:%M:%S') 📟 🔄 Redémarrage demandé dans 5s..." >> logs/pictureframe.log
        sleep 5 # Pause de sécurité pour éviter une boucle rapide en cas de crash
        continue
    fi

    echo "[start_pictureframe] Redémarrage demandé. Relance de l'application dans 2 secondes..." >> logs/pictureframe.log
    sleep 2
done
