# 🖼️ PictureFrame – Cadre photo connecté intelligent

PictureFrame est une application Python conçue pour transformer un Raspberry Pi en un cadre photo numérique intelligent et personnalisable. Il peut afficher des photos depuis de multiples sources et être contrôlé depuis son interface web.

Le script de démarrage est `start_pictureframe.sh` et les journaux utilisent
`logs/pictureframe.log`. Après une mise à niveau, relancez `sudo ./setup.sh`
et redémarrez. Setup migre le lanceur Sway et les noms des fichiers NGINX/sudoers.
Arrêtez l'ancienne application avant la mise à niveau : les anciens et nouveaux
processus ne doivent pas fonctionner ensemble car les fichiers PID/statut ont changé.
Le préfixe EXIF historique est conservé pour les photos déjà préparées.

<img src="static/pictureframe_logo.svg" alt="PictureFrame Logo" width="300" style="display: block; margin: auto;">


---

## 📖 Table des matières

- [✨ Fonctionnalités Principales](#-fonctionnalités-principales)
- [🧰 Technologies utilisées](#-technologies-utilisées)
- [🚀 Installation](#-installation)
- [🔧 Configuration](#-configuration)
- [❓ Dépannage (FAQ)](#-dépannage-faq)
- [🛣️ Feuille de Route](#️-feuille-de-route)
  - [Juin 2025](#-juin-2025-)
  - [Juillet 2025](#-juillet-2025---version-actuelle)
  - [Août 2025](#️-août-2025----sortie-prévue-le-15-aoüt)

---

## ✨ Fonctionnalités Principales

PictureFrame est riche en fonctionnalités pour offrir une expérience complète et personnalisable :

#### 🖼️ **Affichage & Diaporama**
- **Multi-sources :** Affichez des photos depuis [Immich](https://immich.app/), une clé USB ou un smartphone.
- **Imports Immich manuels :** Utilisez le bouton d'import Immich pour actualiser les photos. Aucune synchronisation automatique ne s'exécute en arrière-plan.
- **Horaires actifs :** Les horaires du weekend s'appliquent le vendredi et le samedi ; ceux de semaine du dimanche au jeudi.
- **Commandes du diaporama :** Gauche = photo précédente, Droite = suivante, Espace = pause/lecture. Ces touches affichent les boutons pendant cinq secondes et permettent de naviguer même pendant un fondu ou le chargement d'une photo.
- **Personnalisation avancée :** Réglez la durée d'affichage, les heures d'activité, les transitions (fondu, glissement ou aléatoire à chaque changement de photo), et activez un effet de mouvement "Pan & Zoom".
- **Filtres créatifs :** Appliquez des filtres à vos photos (Noir & Blanc, Sépia, Vintage) et des effets uniques comme le **Polaroid** ou la **Carte Postale**.
- **Gestion des formats :** Prise en charge intelligente des photos portraits (fond flou) et des vidéos (avec son et accélération matérielle optionnelle).

#### ⚙️ **Interface & Contrôle**
- **Interface Web complète :** Une page de configuration locale, sécurisée par mot de passe et organisée en groupes et onglets thématiques pour une navigation intuitive.
- **Gestion de contenu :**
    - **Playlists :** Créez des albums virtuels, réorganisez les photos par glisser-déposer et lancez des diaporamas thématiques avec un écran de titre dynamique (pêle-mêle de photos sur fond en liège).
    - **Favoris :** Marquez vos photos préférées pour qu'elles apparaissent plus souvent.
    - **Légendes :** Ajoutez du texte personnalisé sur vos photos et cartes postales.

#### 🌐 **Connectivité & Interactions**
- **Wi-Fi & Réseau :** Configurez le Wi-Fi, scannez les réseaux et gérez les interfaces réseau directement depuis l'interface.
- **Envoi depuis Smartphone :** Importez des photos directement depuis le navigateur de votre téléphone.

#### 🛠️ **Maintenance & Monitoring**
- **Mise à jour manuelle :** Le code est mis à jour manuellement, sans service de mise à jour à distance dans l'interface.
- **Sauvegarde & Restauration :** Sauvegardez et restaurez l'ensemble de votre configuration.
- **Monitoring système :** Suivez en temps réel la température, l'utilisation du CPU, de la RAM et du disque avec des graphiques d'historique.
- **Logs détaillés :** Accédez aux journaux de chaque service (serveur web, diaporama) pour un dépannage facile.

---

## 🧰 Technologies utilisées

- **Backend :** Python, Flask
- **Frontend :** HTML, TailwindCSS, JavaScript
- **Diaporama :** Pygame
- **Traitement d'image :** Pillow
- **Serveur Web :** NGINX (en tant que reverse proxy)

---

## 🚀 Installation

Il existe deux méthodes pour installer PictureFrame.

### Méthode 1 : Image pré-configurée (Recommandée et plus simple)

Cette méthode est idéale pour une première installation rapide.

1.  **Téléchargez l'image du mois en cours**
    Téléchargez la version du Nouvel An (v1.6.0) directement ici : [pimmich271225.img.xz](https://github.com/gotenash/Pimmich/releases/download/v1.6.0/pimmich271225.img.xz) ou rendez-vous sur la page des Releases de PictureFrame.

2.  **Flashez l'image sur une carte SD**
    Utilisez un logiciel comme Raspberry Pi Imager ou BalenaEtcher pour écrire le fichier image que vous venez de télécharger sur votre carte microSD.

3.  **Démarrez votre Raspberry Pi**
    Insérez la carte SD dans le Raspberry Pi, branchez l'écran et l'alimentation. PictureFrame démarrera automatiquement.

### Méthode 2 : Installation manuelle depuis le dépôt Git

Cette méthode est destinée aux utilisateurs avancés ou à ceux qui souhaitent suivre le développement de près.

#### ✅ Pré-requis

- Un Raspberry Pi (modèle 3B+, 4 ou 5 recommandé) avec **Raspberry Pi OS Trixie (Debian 13)** Desktop (64-bit) — **Version recommandée**.
- Une carte SD, une alimentation, un écran.
- Une connexion Internet.

#### 📝 Étapes d'installation

1.  **Clonez le dépôt**
    Ouvrez un terminal sur votre Raspberry Pi et exécutez :
    ```bash
    git clone https://github.com/gotenash/pimmich.git
    cd pimmich
    ```

2.  **Lancez le script d'installation**
    Ce script installe toutes les dépendances, configure l'environnement et prépare le démarrage automatique.
    ```bash
    chmod +x setup.sh
    sudo ./setup.sh
    ```

3.  **Redémarrez**
    Une fois le script terminé, un redémarrage est nécessaire pour que tous les services se lancent correctement.
    ```bash
    sudo reboot
    ```

### Basculer entre le mode cadre et le bureau

Les outils de maintenance et de contrôle (`add_photos.py`, `reset_admin_password.py`,
`check_*.py`, `verify_he.py`, `test_babel.py`, `_extract.py`) sont dans `scripts/`.
Lancez-les depuis la racine avec `python3 scripts/<nom>.py`. Ils trouvent les
ressources du projet même depuis un autre dossier. `_extract.py` écrit son
fichier temporaire `_untranslated.json` dans `scripts/`. Les points d'entrée
principaux (`app.py`, `local_slideshow.py`, `setup.sh`, `start_pictureframe.sh`)
restent à la racine ; les modules utilitaires restent dans `utils/`.

Après l'installation, utilisez une de ces commandes depuis le dossier du projet :

```bash
bash scripts/enable_auto_frame_start.sh   # Mode cadre : connexion console + Sway
bash scripts/disable_auto_frame_start.sh  # Mode bureau : connexion automatique au bureau
```

Ces scripts demandent les droits sudo et **redémarrent automatiquement** après
avoir modifié le mode de démarrage avec succès. Enregistrez votre travail avant
de les exécuter. L'activation nécessite la
configuration console/Sway, réparée par le script d'activation avant le redémarrage.
Le lanceur active le venv existant si présent, sinon utilise Python global.
En cas d'échec, ouvrez une console avec Ctrl+Alt+F2 puis consultez
`tail -n 100 logs/pictureframe.log` depuis le projet. La désactivation nécessite Raspberry Pi OS
Desktop, pas Lite. PictureFrame et ses réglages sont conservés.

---

## 🔧 Configuration

### 1. Première Connexion

- Au redémarrage, le cadre affichera un QR Code et l'adresse IP du Raspberry Pi.
- Scannez le QR Code ou ouvrez un navigateur sur un autre appareil (PC, smartphone) sur le même réseau et entrez l'adresse IP (ex: `http://192.168.1.XX`).
- Le mot de passe initial est généré aléatoirement lors de l'installation et est stocké dans le fichier `/boot/firmware/credentials.json`. Il est fortement recommandé de le changer via l'interface (onglet `Système` > `Sécurité`).

### 2. Configuration des Sources

- **Immich :** Pour connecter votre serveur Immich, vous aurez besoin de :
    1.  **L'URL de votre serveur** (ex: `http://192.168.1.YY:2283`).
    2.  **Un Token API :** Dans Immich, allez dans `Paramètres du compte` > `Clés API` > `Générer une nouvelle clé`.
    3.  **Le nom technique de l'album** que vous souhaitez afficher.
- **USB :** Branchez une clé USB et utilisez le bouton d'import dans l'onglet `Actions`.

### 3. Personnalisation

Explorez les différents onglets pour personnaliser votre cadre :
- **Diaporama > Affichage :** Réglez les durées, les transitions, les effets...
- **Diaporama > Horloge & Infos :** Activez et configurez l'affichage de l'heure, de la météo ou des marées.
- **Contenu > Sources :** Cochez les sources que vous souhaitez voir dans le diaporama.

---

## ❓ Dépannage (FAQ)

Pour toute question ou problème, consultez notre **Foire Aux Questions (FAQ.md)**. Vous y trouverez des solutions aux problèmes courants (Wi-Fi, affichage, etc.) et des astuces pour utiliser PictureFrame au mieux.

---

## 🛣️ Feuille de Route

#*
- **Projet du :** Gadgetaulab


> 🎂 **SORTIE IMMINENTE : Version Anniversaire - 27 Mai**
> Cette mise à jour majeure marque une étape clé dans le développement de PictureFrame :
> - 📅 **Boost Anniversaire :** Revivez vos souvenirs avec une priorité d'affichage pour les photos prises à la même date les années passées.
> - 🌍 **Métadonnées & Drapeaux :** Affichage personnalisable du lieu, de la date et du drapeau du pays d'origine.
> - 📊 **Monitoring Avancé :** Nouveaux graphiques temps réel pour surveiller la santé de votre Raspberry Pi.
> - 🔌 **Domotique :** Support des prises connectées pour une extinction totale de l'écran.
> - 🖱️ **Playlists UX :** Organisation des albums par glisser-déposer.
> - ⚡ **Hardware Accel :** Lecture vidéo optimisée pour Pi 4 et Pi 5.
> - 🔘 **Bouton Physique :** Support GPIO pour le contrôle matériel de la veille.

---

### 🗓️ Historique des versions

> 🗓️ À partir de juin 2025 — Une version majeure chaque mois

## ✅ Août 2026 - Mises à jour de Stabilité, Performance & Compatibilité Pi 2/3/4/5
- 🚀 **Mise à jour asynchrone & Keep-Alives (anti-timeout) :** Toutes les tâches lourdes (Immich, photo/video prep) s'exécutent en arrière-plan avec pings réseau toutes les 10s pour éviter toute déconnexion de l'interface d'administration.
- 🔁 **Synchronisation intelligente incrémentale :** Seuls les nouveaux médias et les suppressions sont synchronisés, préservant la bande passante, le CPU et l'usure de la carte SD.
- ⚡ **Optimisation de la mémoire GPU (CMA) :** Technique innovante de réduction de fenêtre 1x1 masquée (`pygame.HIDDEN`) pour libérer 100% de la mémoire GPU lors de la lecture vidéo `mpv`, résolvant les crashs et lenteurs sous Wayland/Sway.
- ⏱️ **Lecture vidéo instantanée :** Suppression des appels lents à `ffprobe` au profit d'un Watchdog de sécurité fixe de 90 secondes. La vidéo se lance en moins d'une seconde.
- 📺 **Affichage vidéo robuste devant le diaporama :** Option `--ontop` sélective pour garantir que les vidéos se lisent toujours au premier plan, devant la fenêtre de Pygame sur Pi 1 et 2.
- 🎨 **Transitions optimisées à 30/60 FPS :** Le fondu enchaîné est calculé à 50% de résolution sur Pi 1/2/3 (75% de pixels en moins à traiter) puis mis à l'échelle via l'accélération matérielle de SDL2, avec un sélecteur de FPS dans l'interface admin.
- 🤫 **Zéro bruit CPU sonore au repos :** Le mixeur audio Pygame n'est initialisé qu'à la demande. Évite de charger les serveurs son (Pipewire) en tâche de fond et économise 40% de CPU sur les anciens Pi.
- 🌐 **Vitesse réseau améliorée :** Optimisation de la détection Wi-Fi pour contourner les appels réseau lents sur les systèmes uniquement câblés (Pi 2).
- 📦 **Dépendances optionnelles :** Support HEIF/HEIC optionnel pour garantir le succès de l'installation sur toutes les architectures système, géré à la volée dans `setup.sh`.
- 🇫🇷 **Langue française native :** Configuration et génération automatique de la locale `fr_FR.UTF-8` lors de l'installation pour des dates affichées en français natif.

## ✅ Mai 2026
- 🚀 **Compatibilité Debian Trixie (Debian 13) :**
    - ✅ Migration complète vers **Python 3.13**.
    - ✅ Optimisation du rendu vidéo pour **Sway/Wayland** (DMABUF et V4L2-copy).
    - ✅ Support natif du Raspberry Pi 3 sur les nouveaux noyaux Linux.
    - ✅ Sécurisation non-interactive des commandes `sudo` via règles ciblées.

## ✅ Septembre 2025 - (Sortie prévue le 15 septembre)
- 🎨 **Refonte de l'Interface :** Nouvelle navigation par groupes et onglets pour une expérience plus claire et intuitive.
- 🎵 **Gestion de Playlists Améliorée :**
    - ✅ Nouvel écran de lancement dynamique avec un pêle-mêle de photos sur un fond en liège.
    - ✅ Créez des albums virtuels, visualisez leur contenu, renommez-les et lancez des diaporamas thématiques.
- 🔘 **Bouton Physique :**
    - ✅ Ajout du support pour un bouton physique (via GPIO) pour mettre en veille et réveiller le cadre.
- 🚀 **Optimisations et Stabilité :**
    - ✅ Amélioration de la réactivité de l'onglet "Système" grâce à une lecture optimisée des logs.
    - ✅ Nombreuses corrections de bugs pour une meilleure stabilité générale.

## 🛠️✅ Août 2025  - (Version précédente)
�
- ✅ Gestion des vidéos
-  Ajout d'une vignette lors de lecture de la vidéo (onglet Actions)
- ✅ Gestion accélération matérielle pour Pi3
- ✅ Ajout traduction de l'application (Anglais et Espagnol)
- ✅ Ajout QR Code première connexion
- ✅ Ajout de l'effet "Carte postale" pour toutes les sources de photos
- ✅ Ajout de la fonctionnalité "Ajout de texte"
- ✅ Ajout d'un bouton "Redémarrer l'appli Web"
- ✅ Ajout de l'onglet Favoris (augmentation fréquence d'affichage d'une photo)
- ✅ Modification météo et marées pour afficher 3 jours de prévisions
- ✅ Corrections des bugs
    - ✅ Heure début d'affichage
    - ✅ Effacement des logs dans l'onglet système sans problème de container


## ✅ Juillet 2025  - Version actuelle

- ✅ 🧭 Ajout de la configuration Wi-Fi depuis l’interface Web  
- ✅ 🗂️ Réorganisation de la page de configuration en onglets  
- ✅ ⏰🌤️ Affichage de l’heure et de la météo sur l’écran
- ✅ Ajout NGINX, plus besoin de mettre le numéro du port (50000)
- ✅ Ajout des filtres (NB, Sépia, Polaroid ...)
- ✅ Ajout des différents boutons supprimer
- ✅ Ajout d'une option de sauvegarde de la configuration
- ✅ Ajout d'un menu changement du mot de passe
- ✅ Ajout de la création du credenrials.json pendant le setup
- ✅ Ajout effet de transition
- ✅ Ajout détection automatique de la résolution
- ✅ Ajout de l'import à partir d'un smartphone (en admin et mode invité)
- ✅ Interface de validation des photos proposées en mode invité
- ✅ Ajout des logs dans l'onglet Système
- ✅ Ajout des stats du Raspberry (température, stockage Ram, charge processeur)

## ✅ Juin 2025 –

- ✅ Aperçus des photos avec suppression possible  
- ✅ Véritable mise en veille de l’écran (gestion via `wlr-randr`)  
- ✅ Paramètre de hauteur utile de l’écran (% d’écran utilisé)  
- ✅ Correction de l’orientation via EXIF et préparation des images  



 
## 💡 Idées pour les versions suivantes

- 📱 Création d’une APK Android pour contrôler le cadre 
- PictureFrame télécomande
- PictureFrame Android TV
- Import Google Photos
- Import PhotoPrism    



### Récupérer la Clef API (Token Immich)

🧭 1. Se connecter à l'interface web d’Immich

⚙️ 2. Accéder à la page "Paramètres du compte"
Une fois connecté :

Clique sur l’icône de profil (en haut à droite) ou ton nom d'utilisateur.

![Paramètre du compte](https://drive.google.com/uc?id=1_c12UZ7g8IwsL99xP55eB4qqacGAY8Kc)


Sélectionne “Account settings” ou “Paramètres du compte”.

![Menu Clef API](https://drive.google.com/uc?id=1rofAi6HNhvJbBh2D_AUsedj3HwSrQHjP)


🧪 3. Générer un nouveau token API
Dans la section "API Key" ou "Clés API" :

![Menu Clef API](https://drive.google.com/uc?id=1HrBVgvR4UXdkhLj-4KDohufr5nt57t2G)

Clique sur “Generate new API Key” ou “Générer une nouvelle clé API”.
![Menu Clef API](https://drive.google.com/uc?id=1dRBQMs0dsdM7vKlEuUzBnMmzzH3RNplc)



Donne un nom à ta clé, par exemple :
PictureFrame

✅ Une fois générée, une clé s'affiche. C’est le token à copier.

![Menu Clef API](https://drive.google.com/uc?id=1hyt14hFPN3XEBu_0rh9XYIgLdXJau22y)

⚠️ Attention

Tu ne pourras plus voir cette clé après avoir quitté la page. Si tu la perds, il faudra en générer une nouvelle.

Ne partage jamais ce token publiquement. Il donne un accès total à tes albums Immich.

Le mieux est de créer un compte Immich réservé au cadre photo avec accès à un seul album que tu pourras alimenter à partir d'un autre compte.

### Se connecter à PictureFrame

Dans un navigateur taper l'adresse ip du raspberry : http://xxx.xxx.xxx.xxx:7090

![Menu Clef API](https://drive.google.com/uc?id=1VynC6umiYqPaln_kAb_DDd990YUkbT88)


### Page de configuration

## configuration du diaporama

Dans ce cadre vous pourrez régler le temps d'affichage de chaque photo (pour l'instant on ne peut descendre en dessous de 10 secondes surement du temps de traitement des photos porttrait pour générer le fond flou). Vous pouvez aussi défoinir les heures où le diaporama fonctionnera.

![Menu Clef API](https://drive.google.com/uc?id=1t_7MCKNNfHfTi5Pjc7_hDxbDzU18UvO7)

## configuration de l'import des photos

![Menu Clef API](https://drive.google.com/uc?id=1AwUgYbzGcdskt99q32VlaOc7jM303Tbd)
