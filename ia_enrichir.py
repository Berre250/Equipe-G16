#!/usr/bin/env python3
"""Enrichissement par l'IA locale : explication du score et recommandation d'arôme, pour chaque tendance.

Le score de durabilité est calculé par la formule de collect_trends.py : l'IA ne le calcule pas et ne le
modifie pas. Elle reçoit les vrais chiffres d'une tendance (score, sous-scores, croissance, stade,
sources) et les données du catalogue simulé, et rédige :
  - explication    : 2 ou 3 phrases pour Camille (marketing), qui disent pourquoi la tendance va durer
                     ou non, en citant les chiffres fournis ;
  - recommandation : l'arôme à utiliser et, si la matière est sous tension, l'alternative à proposer.

Le modèle tourne en local avec Ollama (aucune donnée envoyée à l'extérieur). Il est lent sans carte
graphique (20 à 40 s par tendance), donc les textes sont pré-calculés après chaque collecte et lus
ensuite instantanément par l'API et par resultats/radar.json.

Sortie : resultats/ia_enrichissement.json  {trend_id: {explication, recommandation, modele, genere_le}}
Usage :
  python ia_enrichir.py                     # toutes les tendances (les textes déjà générés sont gardés)
  python ia_enrichir.py --only yuzu,sudachi
  python ia_enrichir.py --force             # tout régénérer
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import catalogue as cg

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("TRENDS_DIR", BASE_DIR / "resultats"))
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.getenv("IA_MODEL", "qwen2.5:7b")

SYSTEM = """Tu es analyste de tendances pour l'équipe marketing de Givaudan (arômes et parfums).
Tu écris pour Camille, cheffe de produit marketing. Règles strictes :
- Utilise UNIQUEMENT les chiffres et faits fournis. N'invente aucun chiffre, aucune source, aucun produit.
- Le score est calculé par une formule : ne le recalcule pas, explique-le.
- Français simple, sans jargon, phrases courtes.
- Si la confiance des données est basse, dis-le.
Réponds uniquement en JSON : {"explication": "...", "recommandation": "..."}"""


def facts(t: dict, arom: dict) -> str:
    lines = [
        f"Tendance : {t['trend_name']} (univers : {t['category']})",
        f"Score de durabilité : {t['score']}/100 ; stade : {t['stage']} ; confiance des données : {t['confidence']}",
        f"Sous-scores : évolution {t['evolution_score']}/100 (croissance), récurrence {t['recurrence_score']}/100 "
        f"(temps passé près du pic), diffusion {t['diffusion_score']}/100 (sources et médias)",
        f"Croissance de l'intérêt : {t['growth_5y'] or 'inconnue'} % sur 5 ans, {t['growth_12m'] or 'inconnue'} % sur 12 mois",
        f"Pic d'intérêt DÉJÀ ATTEINT (date passée) : {t['peak_period'] or 'inconnu'}",
        f"Sources : {t['sources'].replace(';', ', ') or 'aucune'} ; presse : {t['news_articles_30d'] or 0} articles "
        f"sur 30 jours dans {t['news_publishers_30d'] or 0} médias",
    ]
    if t.get("tiktok_verdict"):
        lines.append(f"Commentaires TikTok : {t['tiktok_verdict']} (moquerie {t['tiktok_moquerie_pct']} %, "
                     f"intention d'achat {t['tiktok_intention_pct']} %)")
    p = arom.get("arome_principal")
    if p:
        lines.append(f"Arôme Givaudan correspondant (catalogue simulé) : {p['nom']} ; "
                     f"{'au catalogue, délai 1 mois' if p['au_catalogue'] else 'à développer, délai 6 mois'} ; "
                     f"disponibilité {p['disponibilite']} ; risque de récolte {p['risque_recolte']} ; "
                     f"{p['prix_kg_eur']:.0f} €/kg")
        if arom.get("matiere_sous_tension"):
            lines.append("La matière principale est sous tension (rare ou récolte à risque).")
        for a in arom.get("alternatives", []):
            lines.append(f"Alternative : {a['nom']} ; {'au catalogue' if a['au_catalogue'] else 'à développer'} ; "
                         f"disponibilité {a['disponibilite']} ; {a['prix_kg_eur']:.0f} €/kg ; "
                         f"faisabilité {a['score_faisabilite']}/100")
    else:
        lines.append("Aucun arôme correspondant dans le catalogue simulé.")
    lines.append("\nRédige : explication (2 à 3 phrases : la tendance va-t-elle durer et pourquoi) ; "
                 "recommandation (1 à 2 phrases : quel arôme utiliser ; ne propose une alternative QUE si la "
                 "ligne « matière sous tension » figure ci-dessus ; si aucun arôme, dis qu'il faut en développer un).")
    return "\n".join(lines)


def ask(client, prompt: str) -> dict:
    resp = client.chat(model=MODEL, format="json", options={"temperature": 0.2},
                       messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}])
    data = json.loads(resp["message"]["content"])
    return {"explication": str(data.get("explication", "")).strip(),
            "recommandation": str(data.get("recommandation", "")).strip()}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="trend_id ou noms séparés par des virgules")
    ap.add_argument("--force", action="store_true", help="régénérer même les textes déjà produits")
    args = ap.parse_args()

    with open(DATA_DIR / "trends_summary.csv", encoding="utf-8-sig", newline="") as f:
        trends = list(csv.DictReader(f))
    if args.only:
        wanted = {cg_slug(x) for x in args.only.split(",")}
        trends = [t for t in trends if t["trend_id"] in wanted]
    # Les plus hauts scores d'abord : si le traitement est interrompu, les tendances clés sont prêtes
    trends.sort(key=lambda t: -int(t["score"] or 0))
    scores = {t["trend_id"]: int(t["score"] or 0) for t in trends}
    cat = cg.load_catalogue()

    out_path = DATA_DIR / "ia_enrichissement.json"
    done = cg.load_ia(DATA_DIR)
    from ollama import Client
    client = Client(host=OLLAMA_HOST)
    print(f"Enrichissement de {len(trends)} tendances avec {MODEL} (20 à 40 s par tendance sans carte graphique)")
    for i, t in enumerate(trends, 1):
        prompt = facts(t, cg.aromes_for_trend(t["trend_id"], scores, cat))
        h = hashlib.sha1(prompt.encode()).hexdigest()[:12]
        if not args.force and done.get(t["trend_id"], {}).get("hash") == h:
            print(f"[{i}/{len(trends)}] {t['trend_name']} : déjà à jour")
            continue
        try:
            res = ask(client, prompt)
        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ("unable to allocate", "error loading model", "not found", "connect")):
                sys.exit(f"[ERREUR] Le modèle {MODEL} ne peut pas tourner : {e}\n"
                         "Fermez des applications ou essayez : set IA_MODEL=qwen2.5:3b")
            print(f"[{i}/{len(trends)}] {t['trend_name']} : échec ({e}), on passe")
            continue
        done[t["trend_id"]] = dict(res, modele=MODEL, genere_le=datetime.now().isoformat(timespec="minutes"), hash=h)
        out_path.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")  # sauvegarde au fil de l'eau
        print(f"[{i}/{len(trends)}] {t['trend_name']} : {res['explication'][:110]}...")
    print(f"\nÉcrit : {out_path}")


def cg_slug(x: str) -> str:
    import collect_trends as ct
    return ct.slug(x)


if __name__ == "__main__":
    main()
