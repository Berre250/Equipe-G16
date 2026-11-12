"""API de la brique Data : tendances émergentes et score de durabilité (périmètre Givaudan).

Lit les CSV produits par collect_trends.py (dossier `resultats/`, ou TRENDS_DIR) : c'est le même
dossier par défaut que celui où collect_trends.py écrit.

Lancement :
    python trends_api.py            # http://127.0.0.1:8001  (Swagger : /docs)
Export du contrat pour Tech :
    python trends_api.py --export-openapi openapi.json
"""

import csv
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

import collect_trends as ct

DATA_DIR = Path(os.getenv("TRENDS_DIR", Path(__file__).resolve().parent / "resultats"))
SOURCE_LABELS = {"google_trends": "Google Trends", "wikipedia": "Wikipedia", "google_news": "Google News",
                 "tiktok": "TikTok", "pinterest": "Pinterest"}

Stage = Literal["émergente", "croissance", "plateau", "déclin", "inconnu"]
Confidence = Literal["basse", "moyenne", "élevée"]


# ---------------------------------------------------------------- modèles (= le contrat du Swagger)
class TrendSummary(BaseModel):
    trend_id: str = Field(description="Identifiant stable (sans accents ni espaces)", examples=["peptide_serum"])
    trend_name: str = Field(examples=["peptide serum"])
    category: str = Field(description="Univers Givaudan", examples=["Beauté et actifs"])
    score: int = Field(ge=0, le=100, description="Score de durabilité : 40 % évolution, 30 % récurrence, 30 % diffusion",
                       examples=[64])
    growth_5y: int | None = Field(None, description="Croissance en % entre le début et la fin de la série (5 ans)",
                                  examples=[1173])
    growth_12m: int | None = Field(None, description="Croissance moyenne en % sur 12 mois, toutes sources", examples=[41])
    evolution_score: int = Field(ge=0, le=100, description="Sous-score : croissance 12 mois et 5 ans", examples=[48])
    recurrence_score: int = Field(ge=0, le=100, description="Sous-score : durée passée au-dessus de 40 % du pic",
                                  examples=[64])
    diffusion_score: int = Field(ge=0, le=100, description="Sous-score : sources en croissance et nombre de médias",
                                 examples=[87])
    early_signal_score: int | None = Field(None, description="Niveau récent des signaux précoces (TikTok, Pinterest), "
                                           "si disponibles", examples=[72])
    stage: Stage = Field(description="Stade du cycle de vie", examples=["plateau"])
    confidence: Confidence = Field(description="Fiabilité selon le nombre de sources", examples=["moyenne"])
    sources: list[str] = Field(description="Sources utilisées", examples=[["Google Trends", "Google News"]])
    n_sources: int = Field(examples=[2])
    news_articles_30d: int | None = Field(None, description="Articles de presse sur 30 jours", examples=[10])
    news_publishers_30d: int | None = Field(None, description="Médias distincts sur 30 jours", examples=[10])
    news_articles_365d: int | None = Field(None, description="Articles de presse sur 12 mois (plafonné à 100)",
                                           examples=[35])
    peak_period: str | None = Field(None, description="Mois du pic (AAAA-MM-JJ)", examples=["2026-03-01"])
    data_points: int = Field(description="Nombre de mois de données", examples=[61])
    wiki_articles: list[str] = Field(description="Articles Wikipedia utilisés (langue:titre)", examples=[[]])
    recommendation: str = Field(examples=["À surveiller : signal prometteur, à confirmer avec d'autres sources"])
    tiktok_comments: int | None = Field(None, description="Commentaires TikTok analysés (comment_analyzer.py)",
                                        examples=[420])
    tiktok_authenticity: int | None = Field(None, ge=0, le=100, description="Part des avis sincèrement positifs "
                                            "(appréciation + intention d'achat) parmi les commentaires qui donnent "
                                            "un avis", examples=[78])
    tiktok_moquerie_pct: int | None = Field(None, description="Part des commentaires moqueurs ou ironiques (%)",
                                            examples=[9])
    tiktok_intention_pct: int | None = Field(None, description="Part des commentaires avec intention d'achat ou "
                                             "d'essai (%)", examples=[21])
    tiktok_verdict: str | None = Field(None, examples=["engouement sincère avec intention d'achat"])
    collected_at: str = Field(description="Date de la collecte", examples=["2026-11-12"])


class ScoreRequest(BaseModel):
    trend_name: str = Field(min_length=1, description="Nom de la tendance (casse et accents ignorés)",
                            examples=["peptide serum"])
    category: str | None = Field(None, description="Univers Givaudan, utilisé si la tendance est nouvelle",
                                 examples=["Beauté et actifs"])
    auto_collect: bool = Field(True, description="Si la tendance est inconnue, la collecter automatiquement "
                               "(Google Trends, Wikipedia, Google News). Prend de 10 s à 1 min.")


class ScoreResponse(BaseModel):
    trend_name: str = Field(examples=["peptide serum"])
    score: int = Field(ge=0, le=100, examples=[64])
    growth_5y: int | None = Field(None, examples=[1173])
    source: str = Field(description="Sources utilisées, séparées par des points-virgules",
                        examples=["Google Trends; Google News"])
    recommendation: str = Field(examples=["À surveiller : signal prometteur, à confirmer avec d'autres sources"])
    stage: Stage = Field(examples=["plateau"])
    confidence: Confidence = Field(examples=["moyenne"])
    tiktok_authenticity: int | None = Field(None, description="Voir TrendSummary", examples=[78])
    tiktok_verdict: str | None = Field(None, examples=["engouement sincère avec intention d'achat"])


class TimeseriesPoint(BaseModel):
    source: str = Field(examples=["Google Trends"])
    period: str = Field(description="Mois (AAAA-MM-JJ)", examples=["2026-10-01"])
    value: float = Field(description="Valeur brute de la source", examples=[61.0])
    value_norm: float = Field(description="Valeur ramenée à 100 pour le pic de la source", examples=[61.0])


class Health(BaseModel):
    status: str = Field(examples=["ok"])
    trends: int = Field(description="Nombre de tendances chargées", examples=[20])
    collected_at: str | None = Field(None, examples=["2026-11-12"])


# ---------------------------------------------------------------- chargement des CSV
def slug(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def _int(x):
    return int(float(x)) if x not in ("", None) else None


_cache: dict = {}


def _read(name: str) -> list[dict]:
    path = DATA_DIR / name
    if not path.exists():
        raise HTTPException(503, f"Données absentes : lance d'abord `python collect_trends.py` ({path}).")
    mtime = path.stat().st_mtime
    if _cache.get(name, (None,))[0] != mtime:
        with open(path, encoding="utf-8-sig", newline="") as f:
            _cache[name] = (mtime, list(csv.DictReader(f)))
    return _cache[name][1]


def _trend(r: dict) -> TrendSummary:
    sources = [SOURCE_LABELS.get(s, s) for s in r["sources"].split(";") if s]
    return TrendSummary(
        trend_id=r["trend_id"], trend_name=r["trend_name"], category=r["category"], score=_int(r["score"]),
        growth_5y=_int(r["growth_5y"]), growth_12m=_int(r["growth_12m"]),
        evolution_score=_int(r["evolution_score"]), recurrence_score=_int(r["recurrence_score"]),
        diffusion_score=_int(r["diffusion_score"]), early_signal_score=_int(r["early_signal_score"]),
        stage=r["stage"], confidence=r["confidence"], sources=sources, n_sources=_int(r["n_sources"]),
        news_articles_30d=_int(r["news_articles_30d"]), news_publishers_30d=_int(r["news_publishers_30d"]),
        news_articles_365d=_int(r["news_articles_365d"]), peak_period=r["peak_period"] or None,
        data_points=_int(r["data_points"]), wiki_articles=[w for w in r["wiki_articles"].split(";") if w],
        recommendation=r["recommendation"], collected_at=r["collected_at"],
        tiktok_comments=_int(r.get("tiktok_comments")), tiktok_authenticity=_int(r.get("tiktok_authenticity")),
        tiktok_moquerie_pct=_int(r.get("tiktok_moquerie_pct")),
        tiktok_intention_pct=_int(r.get("tiktok_intention_pct")), tiktok_verdict=r.get("tiktok_verdict") or None)


def _find(name: str) -> TrendSummary:
    rows = _read("trends_summary.csv")
    key = slug(name)
    for r in rows:
        if r["trend_id"] == key:
            return _trend(r)
    raise HTTPException(404, f"Tendance inconnue : « {name} ». Disponibles : "
                             + ", ".join(r["trend_name"] for r in rows))


# ---------------------------------------------------------------- API
app = FastAPI(
    title="API Data - Détecteur de tendances (Givaudan)",
    description="Score de durabilité des tendances émergentes (saveurs, parfumerie, actifs beauté, boissons), "
                "calculé à partir de Google Trends, Wikipedia, Google News et de signaux manuels "
                "(TikTok, Pinterest). Les données sont recalculées par `collect_trends.py`.",
    version="1.0.0",
)


@app.get("/", include_in_schema=False)
def root():
    """La racine renvoie vers le Swagger."""
    return RedirectResponse("/docs")


def _collect(name: str, category: str | None) -> TrendSummary:
    """Collecte une nouvelle tendance à la demande et l'ajoute aux résultats."""
    gt = ct.read_gt_csvs(ct.gt_patterns(None))
    kw = dict(name=name.strip(), category=category or ct.AUTRE, wiki_fr=None, wiki_en=None,
              news_query=name.strip())
    rows, row = ct.collect_one(kw, gt, ct.read_manual(str(ct.BASE_DIR / "signaux_manuels.csv")), sleep=0.3,
                               tiktok=ct.load_tiktok_signals(DATA_DIR))
    ct.save_results(DATA_DIR, rows, [row])
    return _find(name)


@app.get("/health", response_model=Health, tags=["système"])
def health():
    """Vérifie que les données sont chargées."""
    rows = _read("trends_summary.csv")
    return Health(status="ok", trends=len(rows), collected_at=rows[0]["collected_at"] if rows else None)


@app.get("/trends", response_model=list[TrendSummary], tags=["tendances"])
def list_trends(
    category: str | None = Query(None, description="Filtrer par univers", examples=["Beauté et actifs"]),
    stage: Stage | None = Query(None, description="Filtrer par stade"),
    min_score: int = Query(0, ge=0, le=100, description="Score minimum"),
    limit: int = Query(50, ge=1, le=200),
):
    """Liste des tendances, triées par score décroissant."""
    out = [_trend(r) for r in _read("trends_summary.csv")]
    if category:
        out = [t for t in out if slug(t.category) == slug(category)]
    if stage:
        out = [t for t in out if t.stage == stage]
    out = [t for t in out if t.score >= min_score]
    return sorted(out, key=lambda t: t.score, reverse=True)[:limit]


@app.get("/trends/{trend_id}", response_model=TrendSummary, tags=["tendances"])
def get_trend(trend_id: str):
    """Détail d'une tendance, avec les sous-scores qui expliquent le score."""
    return _find(trend_id)


@app.get("/trends/{trend_id}/timeseries", response_model=list[TimeseriesPoint], tags=["tendances"])
def get_timeseries(trend_id: str, source: str | None = Query(None, examples=["google_trends"])):
    """Courbes mois par mois (pour les graphiques), une série par source."""
    t = _find(trend_id)
    rows = [r for r in _read("trends_timeseries.csv") if r["trend_id"] == t.trend_id
            and (not source or r["source"] == source)]
    return [TimeseriesPoint(source=SOURCE_LABELS.get(r["source"], r["source"]), period=r["period"],
                            value=float(r["value"]), value_norm=float(r["value_norm"])) for r in rows]


@app.post("/trends/score", response_model=ScoreResponse, tags=["tendances"])
def score(req: ScoreRequest):
    """Score d'une tendance à partir de son nom : c'est l'appel principal pour l'application.

    Si la tendance n'a jamais été collectée et que `auto_collect` vaut true, elle est collectée
    à la demande (Google Trends en cache dans google_trends/), puis ajoutée aux résultats."""
    try:
        t = _find(req.trend_name)
    except HTTPException as e:
        if not req.auto_collect or e.status_code not in (404, 503):
            raise
        t = _collect(req.trend_name, req.category)
    return ScoreResponse(trend_name=t.trend_name, score=t.score, growth_5y=t.growth_5y,
                         source="; ".join(t.sources), recommendation=t.recommendation,
                         stage=t.stage, confidence=t.confidence,
                         tiktok_authenticity=t.tiktok_authenticity, tiktok_verdict=t.tiktok_verdict)


if __name__ == "__main__":
    if "--export-openapi" in sys.argv:
        target = sys.argv[sys.argv.index("--export-openapi") + 1]
        Path(target).write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Contrat OpenAPI écrit dans {target}")
    else:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8001)
