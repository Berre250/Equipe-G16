#!/usr/bin/env python3
"""Export des vrais résultats Data vers la base du prototype Tech (dépôt hackathon-app).

Le prototype lit la table PostgreSQL `trends` (13 tendances simulées). Ce script écrit
resultats/integration_tech.sql : des UPDATE qui remplacent, pour les tendances que nous suivons,
le score, ses trois critères, la courbe de 60 mois (déc. 2021 à nov. 2026) et le score de la veille
par nos vraies valeurs, et passent `simule` à false. Les tendances sans données réelles restent simulées.

score_veille = notre score recalculé sans le dernier mois de données (« ce qui a bougé depuis le mois
dernier »), pour le fil du jour du prototype.

Usage : python exporter_sql_tech.py   puis, dans le dépôt hackathon-app :
  docker compose exec -T db psql -U app -d app < integration_tech.sql
"""

import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import collect_trends as ct

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("TRENDS_DIR", BASE_DIR / "resultats"))
# Nos identifiants -> identifiants du prototype Tech
CORRESPONDANCE = {
    "yuzu": "yuzu", "peptide_serum": "serum-peptides", "matcha": "matcha", "pistache": "pistache-gourmande",
    "kombucha": "kombucha", "chocolat_de_dubai": "dubai-chocolate", "ube": "ube",
}
MOIS = [date(2021 + (11 + i) // 12, (11 + i) % 12 + 1, 1) for i in range(60)]  # déc. 2021 -> nov. 2026


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    summary = {r["trend_id"]: r for r in csv.DictReader(open(DATA_DIR / "trends_summary.csv", encoding="utf-8-sig"))}
    raw = defaultdict(lambda: defaultdict(dict))
    for r in csv.DictReader(open(DATA_DIR / "trends_timeseries.csv", encoding="utf-8-sig")):
        raw[r["trend_id"]][r["source"]][date.fromisoformat(r["period"])] = float(r["value"])

    lines = ["-- Vrais résultats de l'équipe Data (généré par exporter_sql_tech.py, dépôt Equipe-G16).",
             "-- Sources : Google Trends France, Wikipedia, Google News. Collecte : "
             f"{next(iter(summary.values()))['collected_at']}.", "BEGIN;"]
    for ours, theirs in CORRESPONDANCE.items():
        s = summary.get(ours)
        if not s:
            print(f"{ours} : absent des résultats, ignoré")
            continue
        series = raw[ours]
        ref = series.get("google_trends") or series.get("wikipedia") or {}
        norm = ct.normalize(ref) if ref else {}
        last = None
        courbe = []
        for m in MOIS:
            v = norm.get(m, last)
            last = v if v is not None else last
            courbe.append(int(round(v)) if v is not None else 0)
        # Score de la veille : mêmes séries sans le dernier mois
        cut = max(max(sr) for sr in series.values()) if series else None
        before = {src: {p: v for p, v in sr.items() if p < cut} for src, sr in series.items()}
        mets, _, primary = ct.series_metrics(before)
        news = None
        if s["news_publishers_30d"]:
            news = {"publishers_30d": int(s["news_publishers_30d"]), "articles_30d": int(s["news_articles_30d"] or 0),
                    "articles_365d": int(s["news_articles_365d"] or 0)}
        veille = ct.compute_score(mets, primary, news)["score"] if primary else "NULL"
        lines.append(
            f"UPDATE trends SET score = {int(s['score'])}, score_veille = {veille}, "
            f"evolution = {int(s['evolution_score'])}, recurrence = {int(s['recurrence_score'])}, "
            f"diffusion = {int(s['diffusion_score'])}, courbe = ARRAY[{','.join(map(str, courbe))}], "
            f"simule = false WHERE id = '{theirs}';")
        print(f"{ours:<18} -> {theirs:<20} score {s['score']} (veille {veille}), stade {s['stage']}")
    # Explications rédigées par notre modèle local (qwen2.5:7b), visibles dans la fiche tendance du prototype
    ia_path = DATA_DIR / "ia_enrichissement.json"
    ia = json.loads(ia_path.read_text(encoding="utf-8")) if ia_path.exists() else {}
    for ours, theirs in CORRESPONDANCE.items():
        t = ia.get(ours)
        if not t or ours not in summary:
            continue
        sc = int(summary[ours]["score"])
        reco = "suivre" if sc >= 50 else "attendre" if sc >= 35 else "ignorer"  # seuil 35 issu de validate_score.py
        texte = (t.get("explication", "") + " " + t.get("recommandation", "")).strip().replace("'", "''")
        lines.append(f"INSERT INTO analyses (trend_id, recommandation, explication, modele) "
                     f"VALUES ('{theirs}', '{reco}', '{texte}', 'qwen2.5:7b (équipe Data)');")
    lines.append("COMMIT;")
    out = DATA_DIR / "integration_tech.sql"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nÉcrit : {out}")


if __name__ == "__main__":
    main()
