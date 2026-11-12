# Équipe 16 — Brique Data du détecteur de tendances (Givaudan)

Sujet 3 « Tendances émergentes » du hackathon HETIC × Givaudan. La brique Data dit, pour une
tendance (yuzu, sérum aux peptides, matcha…), si elle a des chances de durer : un **score de
durabilité de 0 à 100**, un **stade** (émergente, croissance, plateau, déclin) et une
**recommandation**. Le dashboard « radar de tendances » de l'équipe Tech appelle cette API.

## Fichiers

| Fichier | Rôle |
|---|---|
| `collect_trends.py` | Collecte les signaux (Google Trends, pages vues Wikipedia, Google News, signaux manuels) et calcule le score. Écrit `resultats/trends_summary.csv` et `resultats/trends_timeseries.csv`. |
| `trends_api.py` | API FastAPI qui lit `resultats/` (port 8001, Swagger sur `/docs`). Collecte à la demande les tendances inconnues. |
| `openapi.json` | Contrat d'interface pour Tech, généré par `python trends_api.py --export-openapi openapi.json`. |
| `comment_analyzer.py` | Classe les commentaires TikTok (appréciation, moquerie, intention d'achat…) avec un LLM local. Écrit `resultats/tiktok_signals.csv`. |
| `ia_enrichir.py` | **IA locale** (`qwen2.5:7b` via Ollama) : rédige pour chaque tendance l'explication du score et la recommandation d'arôme. Écrit `resultats/ia_enrichissement.json`. |
| `catalogue_aromes.csv`, `catalogue.py` | Catalogue Givaudan **simulé** (26 arômes : prix, disponibilité, délai, risque de récolte) et choix de l'arôme et des alternatives pour une tendance. |
| `exporter_radar.py` | Exporte tout dans `resultats/radar.json` (tendances, courbes, textes de l'IA, arômes, catalogue) pour le prototype Tech, sans serveur. |
| `validate_score.py` | Validation du score sur les 30 cas de `reference_cases.csv` et comparaison V1 / V2. |
| `reference_cases.csv` | Les 30 cas de référence. La colonne `expected` est à remplir avec Product (`durable` / `passagère`). |
| `google_trends/` | Courbes Google Trends (exports manuels et cache automatique). |
| `exemples/commentaires_demo.csv` | 20 commentaires **inventés** pour tester le classement, ce ne sont pas des données réelles. |
| `installer_ollama_E.bat`, `relancer_ollama.bat`, `tester_commentaires.bat` | Windows : installer Ollama et ses modèles sur E:, le redémarrer et reprendre un téléchargement, tester le classement des commentaires. |
| `time_series_FR_*.csv` | Premier export Google Trends (France, 5 ans). |
| `swagger.json` | Réponse factice de la Gate 1 (mardi). |
| `api.py`, `rag.py`, `ingest.py`, `story.txt`… | Exercice d'onboarding Story RAG (voir en bas). |

## Reproduire les résultats

```bash
pip install -r requirements.txt
ollama pull qwen2.5:7b                 # LLM local pour les commentaires (une seule fois)

python comment_analyzer.py             # 1. commentaires TikTok de tiktok_comments/ -> resultats/tiktok_signals.csv
python collect_trends.py               # 2. collecte + score (intègre les commentaires) -> resultats/
python ia_enrichir.py                  # 3. IA locale : explications et recommandations (20 à 30 min sans GPU)
python exporter_radar.py               # 4. resultats/radar.json pour le prototype
python trends_api.py                   # 5. API sur http://127.0.0.1:8001 (Swagger)
python validate_score.py               # 6. validation du score -> resultats/validation_report.md
python comment_analyzer.py --validate labels.csv --baseline   # 7. validation des commentaires (V1/V2)
```

L'étape 1 est facultative : sans commentaires, le score et l'API fonctionnent normalement.

`collect_trends.py` et `trends_api.py` utilisent le même dossier : `resultats/` à côté des
scripts, ou celui indiqué par la variable d'environnement `TRENDS_DIR`.
`--only "yuzu,matcha"` met à jour ces tendances sans effacer les autres, et accepte des mots-clés
qui ne sont pas dans la liste prévue.

## Google Trends automatique

Pour chaque mot-clé, la courbe Google Trends (France, 5 ans) est chargée sans intervention :

1. si un export CSV existe déjà dans `google_trends/` (ou `time_series_*.csv` à la racine), il est utilisé ;
2. sinon elle est téléchargée avec `pytrends`, puis **enregistrée dans `google_trends/`** :
   les lancements suivants n'appellent plus Google ;
3. si Google refuse (erreur 429, fréquente : pytrends n'est plus maintenu depuis avril 2025),
   exporter le CSV sur [trends.google.com](https://trends.google.com) (France, 5 dernières années,
   bouton ⤓) et le déposer dans `google_trends/` : il sera lu au prochain lancement.

Côté API, `POST /trends/score` sur une tendance jamais collectée lance la collecte à la demande
(10 s à 1 min) et l'ajoute aux résultats. `"auto_collect": false` désactive ce comportement.
Pensez à committer `google_trends/` : la démo ne dépendra pas de Google le jour J.

Sans aucune courbe (ni Google Trends ni Wikipedia), la recommandation est « Données insuffisantes »
au lieu d'un faux « Signal faible ».

## Commentaires TikTok : appréciation ou moquerie ?

Les likes seuls trompent : une vidéo peut devenir virale parce qu'on se moque du produit.
`comment_analyzer.py` classe chaque commentaire dans une de ces catégories : **appréciation**,
**moquerie** (ironie, sarcasme), **intention** (veut goûter, acheter, demande où trouver),
**critique** (avis négatif sincère) ou **neutre**.
Il en tire, par tendance, un **score d'authenticité** : la part des avis sincèrement positifs
(appréciation + intention) parmi les commentaires qui donnent un avis.

1. Trouver des vidéos très likées sur le [TikTok Creative Center](https://ads.tiktok.com/business/creativecenter)
   (Tendances → Hashtags, secteurs Beauté ou Alimentation & boissons, France).
2. Exporter leurs commentaires (par ex. un scraper de commentaires TikTok sur Apify, crédit gratuit
   mensuel), un fichier par tendance dans `tiktok_comments/` : `yuzu.csv`, `chocolat_de_dubai__video2.csv`…
3. `python comment_analyzer.py` → `resultats/tiktok_signals.csv`, puis relancer `collect_trends.py`.
   Le LLM local est lent sans carte graphique (environ 20 à 30 s par commentaire) : par défaut, seuls les
   50 commentaires les plus likés de chaque tendance sont classés (`--max-per-trend`, 0 = tous).
   Les résultats sont gardés en cache : un commentaire n'est jamais classé deux fois.
   La recommandation et l'API (`tiktok_authenticity`, `tiktok_verdict`…) intègrent le résultat.
   Le score de durabilité n'est pas modifié : il a été validé sans ces données.

**Modèle** : V2 = LLM local `qwen2.5:7b` via Ollama (aucune donnée envoyée à l'extérieur).
V1 = règles par mots-clés et emojis (aucune installation), qui ne comprend pas le contexte ni l'ironie.

**Validation** : `python comment_analyzer.py --labeling-sheet 200` tire 200 commentaires dans
`labels_a_remplir.csv`. Une fois la colonne `label` remplie à la main (renommer en `labels.csv`) :
`python comment_analyzer.py --validate labels.csv --baseline` → exactitude et F1 de la V1 et de la V2
dans `resultats/comments_validation.md`.

**RGPD et conditions d'utilisation** : seuls le texte (mentions @ masquées), les likes du commentaire
et un identifiant haché de la vidéo sont conservés ; `tiktok_comments/` (exports bruts avec pseudos)
est exclu de git. L'API Research de TikTok est réservée aux universitaires : pour un outil en
production, Givaudan devrait passer par un fournisseur de données sous licence.

**Ollama sur un autre disque (ex. E:)** : `installer_ollama_E.bat` installe Ollama dans `E:\ollama\app`
(`OllamaSetup.exe /DIR=...`) et ses modèles dans `E:\ollama\models` (`OLLAMA_MODELS`).

## Pour le prototype Tech

- **Sans serveur (recommandé pour la démo)** : lire
  `https://raw.githubusercontent.com/Berre250/Equipe-G16/main/resultats/radar.json`.
  Pour chaque tendance : `score`, `stage`, sous-scores, `sources`, `courbes` (mois par mois, 0-100),
  `ia.explication`, `ia.recommandation`, `aromes.arome_principal`, `aromes.alternatives`,
  `aromes.matiere_sous_tension`. Le bloc `meta` dit ce qui est réel, simulé ou généré par l'IA.
- **Avec l'API** : `GET /trends`, `GET /trends/{id}`, `GET /trends/{id}/timeseries`,
  `GET /trends/{id}/aromes`, `GET /catalogue`, `POST /trends/score` (voir `openapi.json`).

## Rôle de l'IA

| Usage | Script | Ce que fait l'IA | Ce qu'elle ne fait pas |
|---|---|---|---|
| Expliquer une tendance | `ia_enrichir.py` | Rédige en 2-3 phrases pourquoi la tendance va durer ou non, à partir des vrais chiffres | Elle ne calcule pas le score (formule vérifiable) et n'invente pas de chiffre |
| Recommander un arôme | `ia_enrichir.py` | Choisit l'arôme du catalogue et l'alternative si la matière est rare | Les données du catalogue sont simulées |
| Lire les commentaires TikTok (extension, hors MVP) | `comment_analyzer.py` | Distingue appréciation, moquerie et intention d'achat | Pas encore de vrais commentaires analysés |
| Assistant en langage courant | `api.py` (Amir) | Répond aux questions à partir des fiches | Fiches à régénérer depuis `trends_summary.csv` |

Le modèle tourne **en local** (Ollama, `qwen2.5:7b`) : aucune donnée ne sort du poste. Sans carte
graphique il faut 20 à 40 s par tendance, donc les textes sont **pré-calculés après chaque collecte**
et lus instantanément ensuite.

## Le score

Score = 0,4 × évolution (croissance sur 12 mois et sur 5 ans) + 0,3 × récurrence (temps passé
au-dessus de 40 % du pic) + 0,3 × diffusion (séries en hausse et nombre de médias sur 30 jours).

**V2 (12/11)** : en V1, une tendance vue par une seule source, sans Google News, obtenait une
diffusion de 100/100, ce qui gonflait son score (sérum aux peptides : 68 en V1, 47 en V2). En V2,
la part de séries en hausse se calcule sur au moins 2 séries, et l'absence de presse compte pour 0.
La V1 reste disponible (`compute_score(..., version="v1")`) pour la comparaison du vendredi.

## Validation

`validate_score.py` se place en novembre 2023, calcule le score avec les seules données disponibles à
cette date, puis regarde si la tendance a tenu. **Définition retenue** (fixée avant le calcul) : la
tendance est durable si, 12 à 24 mois plus tard, son niveau reste à au moins 50 % de son pic passé.

| Métrique (28 cas) | Méthode naïve | V1 | V2 |
|---|---|---|---|
| AUC | 0,90 | 0,84 | **0,90** |
| Spearman | 0,82 | 0,59 | 0,68 |
| Exactitude, seuil 35 | — | 71 % | **79 %** |

Lecture honnête : la V2 fait nettement mieux que le hasard et que la V1, mais **pas mieux qu'une méthode
naïve** (niveau actuel / pic). Le score résume bien où en est une tendance dans son cycle ; il ne prédit
pas encore au-delà. La première définition (niveau à 80 % du niveau actuel) donnait une AUC de 0,53 :
elle comptait les modes déjà mortes (dalgona coffee) comme durables. Détail : `resultats/validation_report.md`.
`python validate_score.py --offline` refait le calcul à l'identique sans réseau.

## Limites et biais

- **Couverture** : Google Trends en France uniquement ; Wikipedia fr + en ; Google News fr. Pas d'Asie
  ni des États-Unis, alors que beaucoup de tendances (yuzu, ube) y naissent.
- **Mesure** : les recherches et les pages vues mesurent la curiosité, pas les ventes ni les lancements.
  Google Trends est un indice relatif (0-100), pas un volume.
- **Biais de sélection** : 35 tendances et 30 cas de référence choisis à la main, plutôt des tendances
  déjà connues.
- **Validation** : une seule source historique (Wikipedia), trafic Wikipedia en baisse générale, tendances
  saisonnières (pumpkin spice latte) mal gérées ; le seuil 35 est calibré sur les mêmes 28 cas.
- **Ambiguïté des mots-clés** : « Ube » renvoyait vers l'entreprise japonaise UBE (corrigé : Dioscorea alata) ;
  7 tendances sans article Wikipedia fiable sont calculées sans cette source.
- **Réseaux sociaux** : TikTok et Instagram n'ont pas d'API ouverte (réservée aux chercheurs) ; l'analyse
  des commentaires est un prototype hors MVP.
- **Simulé** : le catalogue Givaudan (prix, disponibilité, délais) est fictif.
- **IA** : textes générés par un modèle de 7 milliards de paramètres ; ils reprennent les chiffres fournis
  mais doivent être relus avant tout usage client.

---

# Exercice d'onboarding : Story RAG API

Pose des questions sur une histoire pour enfants (`story.txt`) via une API FastAPI.
Les passages pertinents sont retrouvés dans une base vectorielle (ChromaDB), puis un
LLM Ollama rédige la réponse.

## Fichiers du projet

| Fichier            | Rôle |
|--------------------|------|
| `story.txt`        | L'histoire pour enfants, source des réponses. Le titre est sur la première ligne, les chapitres commencent par « Chapitre N : … » ou « I. … ». |
| `ingest.py`        | Charge l'histoire dans la base : découpe le texte par chapitre en morceaux d'environ 800 caractères, calcule leurs embeddings avec Ollama et les enregistre dans ChromaDB. Peut être relancé sans créer de doublons. Accepte un autre fichier en argument : `python ingest.py autre.txt`. |
| `clean.py`         | Vide la base (supprime la collection ChromaDB), pour recharger l'histoire ou changer de modèle d'embeddings. |
| `api.py`           | L'API FastAPI avec son Swagger : retrouve les passages proches de la question, puis demande au LLM d'y répondre simplement, comme à un enfant. Contient aussi le prompt système. |
| `list.py`          | Affiche le contenu de la base : modèle d'embeddings utilisé, nombre de morceaux, puis chaque morceau (identifiant, taille, aperçu du texte) groupé par chapitre. Avec `--full`, affiche le texte complet. |
| `rag.py`           | Code partagé par les scripts : connexion à ChromaDB, calcul des embeddings et appel du LLM via Ollama. |
| `config.py`        | Tous les réglages (modèles, chemins, taille des morceaux, nombre de passages), modifiables par variables d'environnement. |
| `requirements.txt` | Dépendances Python : FastAPI, Uvicorn, Ollama, ChromaDB. |
| `.gitignore`       | Exclut de git le venv, la base `chroma_db/`, les caches Python et les fichiers locaux. |
| `chroma_db/`       | Base vectorielle créée par `ingest.py` (non versionnée). |

## Installation

Prérequis : Python 3.10+ et [Ollama](https://ollama.com) lancé en local.

### 1. Créer et activer un environnement virtuel

```bash
python -m venv .venv
```

Puis l'activer selon votre terminal :

| Terminal                  | Commande                          |
|---------------------------|-----------------------------------|
| Windows PowerShell        | `.venv\Scripts\Activate.ps1`      |
| Windows cmd               | `.venv\Scripts\activate.bat`      |
| Git Bash (Windows)        | `source .venv/Scripts/activate`   |
| macOS / Linux             | `source .venv/bin/activate`       |

Si PowerShell refuse d'exécuter le script d'activation, autorisez-le pour votre
utilisateur une fois pour toutes :

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Le nom `(.venv)` apparaît alors au début de l'invite. Pour sortir du venv : `deactivate`.

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 3. Télécharger les modèles Ollama

```bash
ollama pull nomic-embed-text   # modèle d'embeddings
ollama pull qwen2.5:1.5b         # LLM (ou un autre, voir Configuration)
```

## Utilisation

```bash
python ingest.py        # charge story.txt dans la base (chroma_db/)
python list.py          # affiche le contenu de la base (--full pour le texte complet)
python clean.py         # vide la base
python api.py           # lance l'API sur http://127.0.0.1:8000
```

Swagger : http://127.0.0.1:8000/docs

Pour recharger après modification de l'histoire : `python clean.py` puis `python ingest.py`.

## Endpoints

| Méthode | Route     | Rôle                                                   |
|---------|-----------|--------------------------------------------------------|
| GET     | `/health` | Nombre de morceaux en base et modèles utilisés         |
| POST    | `/search` | Passages retrouvés seulement (sans LLM), pour déboguer |
| POST    | `/ask`    | Réponse du LLM + passages sources                      |

Corps de requête : `{"question": "Comment s'appelle le cheval de Léo ?", "top_k": 4}`

## Configuration (variables d'environnement)

| Variable      | Défaut              |
|---------------|---------------------|
| `LLM_MODEL`   | `qwen2.5:1.5b`        |
| `EMBED_MODEL` | `nomic-embed-text`  |
| `OLLAMA_HOST` | `http://localhost:11434` |
| `CHROMA_DIR`  | `./chroma_db`       |
| `STORY_PATH`  | `./story.txt`       |
| `CHUNK_SIZE`  | `800` (caractères)  |
| `TOP_K`       | `4`                 |

Si vous changez `EMBED_MODEL`, relancez `clean.py` puis `ingest.py` : les vecteurs
de deux modèles différents ne sont pas compatibles.
