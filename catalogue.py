"""Catalogue Givaudan SIMULÉ et rapprochement tendance -> arômes.

Le catalogue (catalogue_aromes.csv) est fictif : environ 25 arômes inventés pour le prototype, cohérents
avec les 35 tendances suivies. Les délais suivent les réponses de l'expert Givaudan : 1 mois si l'arôme
existe déjà au catalogue, 6 mois en moyenne s'il faut le développer. Les prix et disponibilités sont
des ordres de grandeur plausibles, pas des données Givaudan.

Pour une tendance, on renvoie :
  - les arômes qui y répondent directement (colonne `tendances`) ;
  - des alternatives de la même famille aromatique, classées par un score de faisabilité :
    50 % disponibilité, 30 % présence au catalogue (délai court), 20 % élan de la tendance liée.
"""

import csv
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CATALOGUE_PATH = BASE_DIR / "catalogue_aromes.csv"
DATA_DIR = Path(os.getenv("TRENDS_DIR", BASE_DIR / "resultats"))
DISPO = {"élevée": 1.0, "moyenne": 0.6, "faible": 0.2}


def load_catalogue(path: Path = CATALOGUE_PATH) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rows.append(dict(
                arome_id=r["arome_id"], nom=r["nom"], famille=r["famille"], univers=r["univers"],
                tendances=[t for t in r["tendances"].split(";") if t],
                au_catalogue=r["au_catalogue"].strip().lower() == "oui",
                prix_kg_eur=float(r["prix_kg_eur"]), disponibilite=r["disponibilite"],
                delai_mois=int(r["delai_mois"]), origine_matiere=r["origine_matiere"],
                saisonnalite=r["saisonnalite"], risque_recolte=r["risque_recolte"], note=r["note"] or None,
                simule=True))
    return rows


def _faisabilite(a: dict, scores: dict[str, int]) -> float:
    elan = max((scores.get(t, 0) for t in a["tendances"]), default=0) / 100
    return round(100 * (0.5 * DISPO.get(a["disponibilite"], 0.5) + 0.3 * a["au_catalogue"] + 0.2 * elan))


def aromes_for_trend(trend_id: str, scores: dict[str, int], catalogue: list[dict] | None = None,
                     n_alternatives: int = 3) -> dict:
    """Arômes liés à une tendance et alternatives classées (même famille aromatique)."""
    cat = catalogue or load_catalogue()
    lies = [dict(a, score_faisabilite=_faisabilite(a, scores)) for a in cat if trend_id in a["tendances"]]
    # Arôme principal : celui qui porte le nom de la tendance, sinon celui dont c'est la tendance n°1
    principal = (next((a for a in lies if a["arome_id"] == trend_id), None)
                 or next((a for a in lies if a["tendances"][0] == trend_id), None)
                 or (lies[0] if lies else None))
    familles = {a["famille"] for a in lies}
    pid = principal["arome_id"] if principal else None
    candidats = {a["arome_id"]: a for a in lies if a["arome_id"] != pid}
    for a in cat:
        if a["famille"] in familles and a["arome_id"] != pid and a["arome_id"] not in candidats:
            candidats[a["arome_id"]] = dict(a, score_faisabilite=_faisabilite(a, scores))
    alts = sorted(candidats.values(), key=lambda a: -a["score_faisabilite"])[:n_alternatives]
    bloque = bool(principal and (principal["disponibilite"] == "faible" or principal["risque_recolte"] == "élevé"))
    return dict(trend_id=trend_id, arome_principal=principal, aromes_lies=lies, alternatives=alts,
                matiere_sous_tension=bloque)


def load_ia(data_dir: Path = DATA_DIR) -> dict[str, dict]:
    """Textes générés par l'IA locale (ia_enrichir.py), par trend_id. Vide si le script n'a pas tourné."""
    path = Path(data_dir) / "ia_enrichissement.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
