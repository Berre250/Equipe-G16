#!/usr/bin/env python3
"""Export de toutes les données du radar dans un seul fichier JSON pour le prototype Tech.

resultats/radar.json contient, sans serveur à faire tourner :
  - meta        : date de collecte, version du score, ce qui est réel ou simulé ;
  - tendances   : les 35 tendances (score, stade, sous-scores, sources, recommandation, textes de l'IA,
                  arôme Givaudan et alternatives du catalogue simulé, courbes mensuelles par source) ;
  - catalogue   : le catalogue Givaudan simulé.

Le prototype peut le lire directement depuis GitHub :
  https://raw.githubusercontent.com/Berre250/Equipe-G16/main/resultats/radar.json
Usage : python exporter_radar.py
"""

import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import catalogue as cg

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("TRENDS_DIR", BASE_DIR / "resultats"))
INT_FIELDS = ["score", "growth_5y", "growth_12m", "evolution_score", "recurrence_score", "diffusion_score",
              "n_sources", "news_articles_30d", "news_publishers_30d", "news_articles_365d", "data_points",
              "tiktok_comments", "tiktok_authenticity", "tiktok_moquerie_pct", "tiktok_intention_pct"]


def read(name: str) -> list[dict]:
    with open(DATA_DIR / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    summary = read("trends_summary.csv")
    series = defaultdict(lambda: defaultdict(list))
    for r in read("trends_timeseries.csv"):
        series[r["trend_id"]][r["source"]].append({"period": r["period"][:7], "value_norm": float(r["value_norm"])})
    ia = cg.load_ia(DATA_DIR)
    cat = cg.load_catalogue()
    scores = {r["trend_id"]: int(r["score"] or 0) for r in summary}

    tendances = []
    for r in sorted(summary, key=lambda r: -int(r["score"] or 0)):
        t = {k: (int(float(v)) if k in INT_FIELDS and v not in ("", None) else (None if v == "" else v))
             for k, v in r.items()}
        t["sources"] = [s for s in r["sources"].split(";") if s]
        t["ia"] = {k: ia.get(r["trend_id"], {}).get(k) for k in ("explication", "recommandation", "modele")}
        t["aromes"] = cg.aromes_for_trend(r["trend_id"], scores, cat)
        t["courbes"] = {src: pts for src, pts in series[r["trend_id"]].items()}
        tendances.append(t)

    out = {
        "meta": {
            "collecte": summary[0]["collected_at"] if summary else None,
            "version_score": summary[0].get("score_version") if summary else None,
            "nb_tendances": len(tendances),
            "reel": "Scores, stades, courbes et sources : calculés sur données réelles (Google Trends France, "
                    "Wikipedia, Google News).",
            "simule": "Catalogue Givaudan (arômes, prix, disponibilité, délais) : simulé pour le prototype.",
            "ia": "Explications et recommandations : générées par un LLM local (qwen2.5:7b via Ollama) à partir "
                  "des chiffres ; l'IA ne calcule pas le score.",
            "courbes": "value_norm : intérêt normalisé de 0 à 100 (100 = pic de la série), mois par mois.",
        },
        "tendances": tendances,
        "catalogue": cat,
    }
    path = DATA_DIR / "radar.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    with_ia = sum(1 for t in tendances if t["ia"]["explication"])
    print(f"Écrit : {path} ({len(tendances)} tendances, {with_ia} avec textes de l'IA, {len(cat)} arômes, "
          f"{path.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
