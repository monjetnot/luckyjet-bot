# 🤖 Bot Lucky Jet AUTO — Guide d'installation complet

## Architecture
```
[Railway/Render (cloud)] ← scrape 1win en continu
        ↓  cotes automatiques
  [Bot Telegram]  ←→  [Ton Android]
```
Tout tourne sur un serveur cloud. Toi, tu utilises seulement Telegram.

---

## ÉTAPE 1 — Créer le bot Telegram

1. Ouvre Telegram → recherche **@BotFather**
2. Envoie `/newbot`
3. Nom : ex. `LuckyJet Auto`
4. Username : ex. `lj_auto_bot`
5. **Copie le TOKEN** (ex: `7123456789:AAFdef...`)

---

## ÉTAPE 2 — Récupérer ton Chat ID

1. Ouvre Telegram → recherche **@userinfobot**
2. Envoie `/start`
3. **Note ton Id** (ex: `123456789`)

---

## ÉTAPE 3 — Déployer sur Railway (GRATUIT)

### 3a. Créer un compte
1. Va sur **https://railway.app**
2. Clique "Login" → "Login with GitHub"
3. Crée un compte GitHub si besoin (gratuit)

### 3b. Créer un nouveau projet
1. Sur Railway → clique **"New Project"**
2. Clique **"Deploy from GitHub repo"**
3. Clique **"Configure GitHub App"** → autorise Railway
4. Clique **"Create new repo"** sur GitHub

### 3c. Upload les fichiers
Sur **https://github.com** :
1. Crée un nouveau dépôt (ex: `luckyjet-bot`)
2. Clique "Add file" → "Upload files"
3. Upload ces 4 fichiers :
   - `bot.py`
   - `scraper.py`
   - `requirements.txt`
   - `Dockerfile`
4. Clique **"Commit changes"**

### 3d. Connecter à Railway
1. Retourne sur Railway → "Deploy from GitHub repo"
2. Sélectionne ton repo `luckyjet-bot`
3. Railway va détecter le `Dockerfile` automatiquement

### 3e. Ajouter les variables d'environnement
Sur Railway, dans ton projet :
1. Clique sur ton service → onglet **"Variables"**
2. Clique **"Add Variable"** et ajoute :

| Nom | Valeur |
|-----|--------|
| `TELEGRAM_TOKEN` | `7123456789:AAFdef...` (ton token) |
| `ALERT_CHAT_ID` | `123456789` (ton chat ID) |

3. Clique **"Deploy"**

---

## ÉTAPE 4 — Vérifier que ça fonctionne

1. Va sur Telegram → ouvre ton bot
2. Envoie `/start`
3. Tu verras : _"✅ Les cotes sont collectées automatiquement depuis 1win"_
4. Attends 2-3 minutes → les premières cotes arrivent
5. Envoie `/history` pour voir les cotes collectées
6. Envoie `/analyse` pour le premier rapport

---

## UTILISATION AU QUOTIDIEN (sur Android)

| Commande | Description |
|----------|-------------|
| `/start` | Menu principal |
| `/analyse` | Rapport complet + recommandation |
| `/history` | 15 dernières cotes collectées |
| `/subscribe` | Reçois une analyse tous les 5 tours automatiquement |
| `/unsubscribe` | Désactiver les alertes auto |
| `/myid` | Voir ton Chat ID |

---

## Ce que le bot collecte et analyse

### Collecte automatique
- Le scraper ouvre 1win en arrière-plan (navigateur headless)
- Il écoute le WebSocket du jeu et intercepte les résultats de chaque tour
- Chaque cote est enregistrée automatiquement

### Analyse statistique
- **Fréquences par tranche** : % des tours ≥ 1.2x, 1.5x, 2x, 3x, 5x
- **Comparaison récent vs global** : tendance des 30 derniers tours
- **Tranche sécuritaire** : la plus haute cote avec ≥70% de fréquence récente
- **Confiance** : basée sur la stabilité statistique (coefficient de variation)
- **Alerte streak** : si 4+ tours consécutifs < 2x

### Exemple de rapport
```
✅ RECOMMANDATION
• Tranche sécuritaire : 1.5x
• Confiance : 🟢 Élevée (78%)
```
→ Signifie que dans 78% des 30 derniers tours, la cote était ≥ 1.5x

---

## Option alternative : Render.com (aussi gratuit)

1. Va sur **https://render.com** → créer un compte
2. "New" → "Web Service"
3. Connecte ton repo GitHub
4. Environment : **Docker**
5. Ajoute les variables d'environnement (`TELEGRAM_TOKEN`, `ALERT_CHAT_ID`)
6. Clique "Create Web Service"

---

## ⚠️ Note importante sur le scraping
Le scraper utilise un navigateur automatisé pour lire les données affichées
sur 1win. Si 1win modifie son interface, le scraper peut nécessiter
une mise à jour des sélecteurs CSS dans `scraper.py`.

---

## ⚠️ Rappel responsabilité
Ce bot est un outil d'analyse statistique.
Les % affichés décrivent l'historique passé, pas le futur.
Joue avec des mises responsables.
