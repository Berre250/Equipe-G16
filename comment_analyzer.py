#!/usr/bin/env python3
"""Analyse des commentaires TikTok : like d'appréciation, moquerie ou intention d'achat ?

Entrée : exports CSV/JSON des commentaires (par ex. un scraper Apify), un fichier par tendance,
dans tiktok_comments/. Le nom du fichier donne la tendance : tiktok_comments/yuzu.csv,
tiktok_comments/chocolat_de_dubai__video2.csv (tout ce qui suit "__" est ignoré).
Une colonne `trend` dans le fichier est prioritaire sur le nom du fichier.

Chaque commentaire est classé dans une catégorie :
  appreciation  : aime, admire, trouve ça bon ou beau
  moquerie      : se moque, ironie, sarcasme, trouve ça ridicule ou dégoûtant pour rire
  intention     : veut goûter, acheter, essayer, demande où le trouver ou la recette
  critique      : avis négatif sincère (mauvais goût, trop cher, déçu...)
  neutre        : hors sujet, tag d'un ami sans avis, emoji seul ambigu

Modèles :
  V2 (défaut) : LLM local via Ollama (qwen2.5:7b), catégories complètes, aucune donnée envoyée dehors
  V1 (--baseline) : règles par mots-clés et emojis (aucune installation) ; ne comprend pas le contexte

RGPD : seuls le texte (mentions @ masquées), les likes du commentaire et l'identifiant de la vidéo
sont gardés. Pseudos, avatars et identifiants d'auteur ne sont jamais écrits.

Sorties (resultats/) :
  tiktok_comments_labeled.csv : commentaires anonymisés + catégorie
  tiktok_signals.csv          : une ligne par tendance (parts de chaque catégorie, score d'authenticité),
                                lue par collect_trends.py
Usage :
  python comment_analyzer.py                         # classe tiktok_comments/ avec la V2 (50 plus likés / tendance)
  python comment_analyzer.py --max-per-trend 0       # tous les commentaires (long sans carte graphique)
  python comment_analyzer.py --labeling-sheet 200    # crée la feuille de 200 commentaires à étiqueter
  python comment_analyzer.py --validate labels.csv --baseline   # précision V1 vs V2
"""

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = Path(os.getenv("TRENDS_DIR", BASE_DIR / "resultats"))
IN_DIR = Path(os.getenv("TIKTOK_DIR", BASE_DIR / "tiktok_comments"))
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM = os.getenv("COMMENT_LLM", "qwen2.5:7b")
LABELS = ["appreciation", "moquerie", "intention", "critique", "neutre"]
BATCH = 15
MAX_PER_TREND = int(os.getenv("MAX_PER_TREND", "50"))  # le LLM local est lent : on garde les plus likés

# Noms de colonnes possibles selon les scrapers
TEXT_COLS = ["text", "comment", "commentText", "comment_text", "content", "body"]
VIDEO_COLS = ["videoWebUrl", "video_url", "videoUrl", "submittedVideoUrl", "postUrl", "url", "aweme_id", "video_id"]
LIKES_COLS = ["diggCount", "likes", "likeCount", "like_count", "digg_count"]

PROMPT = """Tu analyses des commentaires TikTok sous des vidéos de nourriture, boissons, parfums ou cosmétiques,
pour savoir si une tendance est appréciée sincèrement ou moquée.
Classe CHAQUE commentaire dans exactement une catégorie :
- appreciation : aime, admire, trouve ça bon/beau ("trop bon", "j'adore", "ça a l'air incroyable 😍")
- moquerie : se moque, ironie, sarcasme ("qui mange ça 💀", "les gens sont prêts à tout pour des vues",
  "ça a le goût de dentifrice mdr", éloges exagérés clairement ironiques)
- intention : veut goûter, acheter, essayer, demande où trouver ou la recette ("je veux tester",
  "où on achète ça ?", "recette svp", "je vais en commander")
- critique : avis négatif sincère, sans moquerie ("trop sucré", "beaucoup trop cher", "déçu")
- neutre : hors sujet, tag d'un ami sans avis, emoji seul ambigu
Attention : 😭 et 💀 peuvent exprimer l'enthousiasme comme la moquerie, regarde le reste du texte.
Réponds uniquement en JSON : {"labels": ["categorie", ...]} avec une catégorie par commentaire, dans l'ordre.

Commentaires :
"""


# ---------------------------------------------------------------- lecture et anonymisation
def slug(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def anonymize(text: str) -> str:
    text = re.sub(r"@[\w.]+", "@user", text)
    text = re.sub(r"https?://\S+", "<lien>", text)
    return re.sub(r"\s+", " ", text).strip()


def pick(row: dict, cols: list[str]):
    for c in cols:
        if c in row and row[c] not in (None, ""):
            return row[c]
    return None


def read_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("items", [])
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def cap_per_trend(comments: list[dict], n: int) -> list[dict]:
    """Garde les n commentaires les plus likés de chaque tendance (n <= 0 : tout garder)."""
    if n <= 0:
        return comments
    by: dict[str, list[dict]] = {}
    for c in comments:
        by.setdefault(c["trend"], []).append(c)
    kept = []
    for trend, cs in by.items():
        cs = sorted(cs, key=lambda c: -c["comment_likes"])
        if len(cs) > n:
            print(f"   {trend} : {len(cs)} commentaires, on garde les {n} plus likés (--max-per-trend)")
        kept += cs[:n]
    return kept


def load_comments(folder: Path) -> list[dict]:
    comments = []
    files = sorted(list(folder.glob("*.csv")) + list(folder.glob("*.json")))
    if not files:
        sys.exit(f"Aucun export dans {folder} : déposez-y un CSV/JSON de commentaires par tendance.")
    for path in files:
        default_trend = path.stem.split("__")[0].replace("_", " ")
        n = 0
        for r in read_rows(path):
            text = pick(r, TEXT_COLS)
            if not text or not str(text).strip():
                continue
            likes = pick(r, LIKES_COLS)
            video = str(pick(r, VIDEO_COLS) or path.stem)
            comments.append(dict(
                trend=(r.get("trend") or default_trend).strip(),
                video_id=hashlib.sha1(video.encode()).hexdigest()[:10],  # pas d'URL ni de pseudo
                text=anonymize(str(text)),
                comment_likes=int(float(likes)) if likes not in (None, "") else 0,
            ))
            n += 1
        trends = sorted({c["trend"] for c in comments[-n:]}) if n else []
        print(f"{path.name} : {n} commentaires -> {', '.join(trends) or default_trend}")
    return comments


# ---------------------------------------------------------------- modèles
class ModelUnavailable(RuntimeError):
    pass


def _fatal(e: Exception) -> bool:
    """Erreurs qui ne se régleront pas en réessayant : modèle absent ou mémoire insuffisante."""
    msg = str(e).lower()
    return any(k in msg for k in ("error loading model", "unable to allocate", "not found", "out of memory",
                                  "requires more system memory", "connection refused", "failed to connect"))


def classify_llm(texts: list[str], cache: dict) -> list[str]:
    """V2 : LLM local via Ollama, par lots, avec cache pour ne jamais reclasser un commentaire."""
    from ollama import Client
    client = Client(host=OLLAMA_HOST)
    todo = [t for t in dict.fromkeys(texts) if f"{LLM}|{t}" not in cache]
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        listing = "\n".join(f"{j + 1}. {t[:300]}" for j, t in enumerate(batch))
        labels = []
        for attempt in range(2):
            try:
                resp = client.chat(model=LLM, format="json", options={"temperature": 0},
                                   messages=[{"role": "user", "content": PROMPT + listing}])
                labels = json.loads(resp["message"]["content"]).get("labels", [])
            except Exception as e:
                if _fatal(e):
                    raise ModelUnavailable(str(e))
                print(f"   erreur Ollama : {e}")
            if len(labels) == len(batch):
                break
        if len(labels) != len(batch):  # réponse mal formée : on reprend un par un
            labels = []
            for t in batch:
                try:
                    resp = client.chat(model=LLM, format="json", options={"temperature": 0},
                                       messages=[{"role": "user", "content": PROMPT + "1. " + t[:300]}])
                    labels.append((json.loads(resp["message"]["content"]).get("labels") or ["neutre"])[0])
                except Exception as e:
                    if _fatal(e):
                        raise ModelUnavailable(str(e))
                    labels.append(None)  # échec ponctuel : pas mis en cache, sera retenté au prochain lancement
        for t, lab in zip(batch, labels):
            if lab is None:
                continue
            lab = str(lab).strip().lower().replace("é", "e")
            cache[f"{LLM}|{t}"] = lab if lab in LABELS else "neutre"
        print(f"   V2 : {min(i + BATCH, len(todo))}/{len(todo)} commentaires classés")
    return [cache.get(f"{LLM}|{t}", "neutre") for t in texts]


# Lexique de la V1 : une liste de mots et d'emojis, sans aucune compréhension du contexte
LEXICON = {
    "intention": ["je veux", "j'veux", "faut que je", "où acheter", "ou acheter", "où on", "ou on trouve",
                  "où trouver", "ou trouver", "recette", "je vais tester", "à tester", "a tester", "je teste",
                  "commander", "j'achète", "j'achete", "dispo où", "where to buy", "need this", "i want", "recipe"],
    "moquerie": ["💀", "🤡", "mdr", "ptdr", "lol", "qui mange", "ridicule", "n'importe quoi", "dégueu", "degueu",
                 "beurk", "🤮", "bizarre", "pour des vues", "cringe", "weird", "gross"],
    "critique": ["trop cher", "trop sucré", "trop sucre", "déçu", "decu", "pas bon", "mauvais", "nul",
                 "overrated", "surcoté", "surcote", "arnaque"],
    "appreciation": ["j'adore", "jadore", "trop bon", "délicieux", "delicieux", "incroyable", "magnifique",
                     "trop beau", "miam", "😍", "🤤", "❤", "🔥", "love", "yummy", "amazing", "best"],
}


def classify_baseline(texts: list[str]) -> list[str]:
    """V1 : règles par mots-clés et emojis (aucune installation). Ne comprend ni l'ironie ni le contexte :
    elle sert de point de comparaison pour montrer ce que le LLM apporte."""
    out = []
    for t in texts:
        low = t.lower()
        hits = {lab: sum(w in low for w in words) for lab, words in LEXICON.items()}
        best = max(hits, key=hits.get)
        out.append(best if hits[best] > 0 else "neutre")
    return out


# ---------------------------------------------------------------- agrégation par tendance
def aggregate(rows: list[dict]) -> list[dict]:
    by_trend: dict[str, list[dict]] = {}
    for r in rows:
        by_trend.setdefault(r["trend"], []).append(r)
    out = []
    for trend, rs in sorted(by_trend.items()):
        c = Counter(r["label"] for r in rs)
        n = len(rs)
        share = {lab: 100 * c[lab] / n for lab in LABELS}
        opinion = c["appreciation"] + c["intention"] + c["moquerie"] + c["critique"]
        # Authenticité : part des réactions positives sincères parmi les commentaires qui donnent un avis
        auth = 100 * (c["appreciation"] + c["intention"]) / opinion if opinion else None
        if auth is None:
            verdict = "pas assez d'avis"
        elif share["moquerie"] >= 30:
            verdict = "buzz moqueur : viralité surtout ironique"
        elif auth >= 70 and share["intention"] >= 10:
            verdict = "engouement sincère avec intention d'achat"
        elif auth >= 60:
            verdict = "accueil plutôt sincère"
        else:
            verdict = "accueil mitigé"
        out.append(dict(
            trend_id=slug(trend), trend_name=trend, n_comments=n, n_videos=len({r["video_id"] for r in rs}),
            appreciation_pct=round(share["appreciation"]), moquerie_pct=round(share["moquerie"]),
            intention_pct=round(share["intention"]), critique_pct=round(share["critique"]),
            neutre_pct=round(share["neutre"]),
            authenticity_score=round(auth) if auth is not None else "", verdict=verdict, model=LLM))
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- validation V1 / V2
def scores(gold: list[str], pred: list[str]) -> dict:
    acc = sum(g == p for g, p in zip(gold, pred)) / len(gold)
    f1s = {}
    for lab in LABELS:
        tp = sum(g == lab and p == lab for g, p in zip(gold, pred))
        fp = sum(g != lab and p == lab for g, p in zip(gold, pred))
        fn = sum(g == lab and p != lab for g, p in zip(gold, pred))
        if tp + fp + fn:
            f1s[lab] = 2 * tp / (2 * tp + fp + fn)
    return dict(acc=acc, macro_f1=sum(f1s.values()) / len(f1s) if f1s else 0, f1=f1s)


def validate(path: str, baseline: bool, cache: dict) -> None:
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8-sig"))
            if (r.get("label") or "").strip().lower() in LABELS]
    if len(rows) < 20:
        sys.exit(f"Seulement {len(rows)} commentaires étiquetés dans {path} : il en faut au moins 20.")
    texts = [r["text"] for r in rows]
    gold = [r["label"].strip().lower() for r in rows]
    try:
        results = {"V2 (LLM " + LLM + ")": scores(gold, classify_llm(texts, cache))}
    except ModelUnavailable as e:
        sys.exit(f"[ERREUR] Le modèle {LLM} ne peut pas tourner : {e} (essayez COMMENT_LLM=qwen2.5:3b)")
    if baseline:
        results["V1 (mots-clés et emojis)"] = scores(gold, classify_baseline(texts))
    lines = [f"# Validation du classement des commentaires — {len(rows)} commentaires étiquetés à la main", "",
             "| Modèle | Exactitude | F1 macro | F1 moquerie | F1 intention |", "|---|---|---|---|---|"]
    for name, s in results.items():
        lines.append(f"| {name} | {s['acc']:.0%} | {s['macro_f1']:.2f} | {s['f1'].get('moquerie', 0):.2f} | "
                     f"{s['f1'].get('intention', 0):.2f} |")
    lines += ["", f"Répartition des étiquettes : {dict(Counter(gold))}",
              "", "La V1 repère des mots et des emojis sans comprendre le contexte : « trop bon 💀 » ou un éloge "
              "ironique la trompent. L'écart avec la V2 mesure ce qu'apporte le LLM."]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "comments_validation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


# ---------------------------------------------------------------- programme principal
def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in-dir", default=str(IN_DIR))
    ap.add_argument("--labeling-sheet", type=int, metavar="N",
                    help="tirer N commentaires au hasard dans labels_a_remplir.csv pour l'étiquetage")
    ap.add_argument("--validate", metavar="LABELS_CSV", help="mesurer la précision sur des commentaires étiquetés")
    ap.add_argument("--baseline", action="store_true", help="ajouter la V1 (mots-clés) à la validation")
    ap.add_argument("--max-per-trend", type=int, default=MAX_PER_TREND,
                    help=f"commentaires gardés par tendance, les plus likés d'abord (défaut {MAX_PER_TREND}, 0 = tous)")
    args = ap.parse_args()

    cache_path = OUT_DIR / "comments_cache.json"
    if OUT_DIR.exists() is False:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    try:
        if args.validate:
            validate(args.validate, args.baseline, cache)
            return
        comments = load_comments(Path(args.in_dir))
        if args.labeling_sheet:
            random.seed(42)
            sample = random.sample(comments, min(args.labeling_sheet, len(comments)))
            path = BASE_DIR / "labels_a_remplir.csv"
            write_csv(path, [dict(trend=c["trend"], text=c["text"], label="") for c in sample])
            print(f"\n{len(sample)} commentaires dans {path}. Remplir la colonne label avec : {', '.join(LABELS)}")
            return
        comments = cap_per_trend(comments, args.max_per_trend)
        print(f"\nClassement de {len(comments)} commentaires avec {LLM} "
              f"(environ 20 à 30 s par commentaire sur un PC sans carte graphique)...")
        try:
            labels = classify_llm([c["text"] for c in comments], cache)
        except ModelUnavailable as e:
            sys.exit(f"\n[ERREUR] Le modèle {LLM} ne peut pas tourner : {e}\n"
                     "  - mémoire insuffisante : fermez des applications (navigateurs, Discord...) et libérez de la "
                     "place sur C: (fichier d'échange de Windows)\n"
                     "  - ou utilisez un modèle plus léger : set COMMENT_LLM=qwen2.5:3b puis relancez\n"
                     "  - modèle absent : ollama pull " + LLM)
        for c, lab in zip(comments, labels):
            c["label"] = lab
        write_csv(OUT_DIR / "tiktok_comments_labeled.csv", comments)
        if len(comments) <= 60:  # petit échantillon : on montre chaque décision
            print("")
            for c in comments:
                print(f"  {c['label']:<13} [{c['trend']}] {c['text'][:90]}")
        signals = aggregate(comments)
        write_csv(OUT_DIR / "tiktok_signals.csv", signals)
        print("\n" + "\n".join(f"{s['trend_name']:<22} {s['n_comments']:>5} comm.  authenticité={s['authenticity_score']}"
                               f"  moquerie={s['moquerie_pct']}%  intention={s['intention_pct']}%  -> {s['verdict']}"
                               for s in signals))
        print(f"\nÉcrit : {OUT_DIR / 'tiktok_signals.csv'}. Relancez collect_trends.py pour l'intégrer au score.")
    finally:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
