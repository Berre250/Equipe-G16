#!/usr/bin/env python3
"""Collecte de signaux de tendances pour le périmètre Givaudan et calcul d'un score explicable.

Sources (aucune clé requise, bibliothèque standard uniquement) :
  - Google Trends  : export CSV (--gt-csv, "time_series_*.csv") ou pytrends (--pytrends, optionnel)
  - Wikipedia      : pages vues mensuelles (API Wikimedia, fr + en)
  - Google News    : flux RSS (articles sur 30 jours / 12 mois, nombre de médias distincts)
  - Signaux manuels: TikTok Creative Center, Pinterest Trends... via --manual signaux_manuels.csv
                     colonnes : keyword,source,period,value   (ex. yuzu,tiktok,2026-10,74)

Sorties (dans --out-dir) :
  - trends_timeseries.csv : une ligne par tendance, source et mois
  - trends_summary.csv    : une ligne par tendance, avec les attributs qui servent au Swagger

Score (0-100, version de départ à calibrer sur des cas passés) =
  0,4 x évolution (croissance 12 mois et 5 ans) + 0,3 x récurrence (durée au-dessus de 40 % du pic)
  + 0,3 x diffusion (part des sources en croissance + nombre de médias distincts sur 30 jours)

Usage :
  python collect_trends.py                                  # tout le bloc de mots-clés
  python collect_trends.py --only "yuzu,matcha" --gt-csv time_series_FR.csv
  python collect_trends.py --keywords-file mes_mots_cles.csv   # name,category,wiki_fr,wiki_en,news_query
"""

import argparse
import csv
import glob
import json
import math
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------- bloc de mots-clés
# wiki_fr / wiki_en : titre d'article imposé. None = recherche automatique, False = ne pas utiliser
# Wikipedia pour ce mot-clé (mot trop ambigu).
FRUITS, GRILL, MER, CUISINE = ("Fruits et légumes", "Saveurs grillées", "Produits de la mer",
                               "Ingrédients de cuisine")
SAVEURS = FRUITS  # catégorie par défaut pour un fichier de mots-clés externe
PARFUM, BEAUTE, BOISSONS = "Parfumerie", "Beauté et actifs", "Boissons et bien-être"
MARCHES = {FRUITS: "marché des fruits et légumes", GRILL: "marché des saveurs grillées",
           MER: "marché des produits de la mer", CUISINE: "marché des ingrédients de cuisine",
           PARFUM: "marché de la parfumerie", BEAUTE: "marché du skincare", BOISSONS: "marché des boissons"}

KEYWORDS = [
    # Fruits et légumes
    dict(name="yuzu", category=FRUITS, wiki_fr="Yuzu", wiki_en="Yuzu", news_query="yuzu"),
    dict(name="sudachi", category=FRUITS, wiki_fr="Sudachi", wiki_en="Sudachi", news_query="sudachi agrume"),
    dict(name="ube", category=FRUITS, wiki_fr=False, wiki_en="Ube", news_query="ube violet saveur"),
    dict(name="pistache", category=FRUITS, wiki_fr="Pistache", wiki_en="Pistachio", news_query="pistache"),
    dict(name="calamansi", category=FRUITS, wiki_fr=None, wiki_en="Calamansi", news_query="calamansi"),
    dict(name="jackfruit", category=FRUITS, wiki_fr=None, wiki_en="Jackfruit", news_query="jackfruit"),
    # Saveurs grillées
    dict(name="gochujang", category=GRILL, wiki_fr="Gochujang", wiki_en="Gochujang", news_query="gochujang"),
    dict(name="BBQ coréen", category=GRILL, wiki_fr=False, wiki_en="Korean barbecue", news_query="barbecue coréen"),
    dict(name="saveur fumée", category=GRILL, wiki_fr=False, wiki_en=False, news_query="saveur fumée"),
    dict(name="chili crisp", category=GRILL, wiki_fr=False, wiki_en=None, news_query="chili crisp"),
    dict(name="yakitori", category=GRILL, wiki_fr="Yakitori", wiki_en="Yakitori", news_query="yakitori"),
    # Produits de la mer
    dict(name="algues nori", category=MER, wiki_fr="Nori", wiki_en="Nori", news_query="algues nori"),
    dict(name="surimi", category=MER, wiki_fr="Surimi", wiki_en="Surimi", news_query="surimi"),
    dict(name="sauce de poisson", category=MER, wiki_fr=None, wiki_en="Fish sauce", news_query="sauce de poisson"),
    dict(name="conserves de poisson", category=MER, wiki_fr=False, wiki_en=False, news_query="conserves de poisson tendance"),
    # Ingrédients de cuisine
    dict(name="miso", category=CUISINE, wiki_fr="Miso", wiki_en="Miso", news_query="miso"),
    dict(name="tahini", category=CUISINE, wiki_fr="Tahin", wiki_en="Tahini", news_query="tahini"),
    dict(name="harissa", category=CUISINE, wiki_fr="Harissa", wiki_en="Harissa", news_query="harissa"),
    dict(name="hot honey", category=CUISINE, wiki_fr=False, wiki_en=False, news_query="hot honey miel piquant"),
    dict(name="furikake", category=CUISINE, wiki_fr=False, wiki_en="Furikake", news_query="furikake"),
    dict(name="chocolat de Dubaï", category=CUISINE, wiki_fr=None, wiki_en=None, news_query="chocolat de Dubaï"),
    # Parfumerie
    dict(name="parfum solide", category=PARFUM, wiki_fr=False, wiki_en=False, news_query="parfum solide"),
    dict(name="oud", category=PARFUM, wiki_fr="Bois d'agar", wiki_en="Agarwood", news_query="parfum oud"),
    dict(name="parfum gourmand", category=PARFUM, wiki_fr=False, wiki_en=False, news_query="parfum gourmand"),
    dict(name="vanille", category=PARFUM, wiki_fr="Vanille", wiki_en="Vanilla", news_query="parfum vanille"),
    dict(name="ambroxan", category=PARFUM, wiki_fr=None, wiki_en="Ambroxan", news_query="ambroxan"),
    # Beauté et actifs
    dict(name="peptide serum", category=BEAUTE, wiki_fr=False, wiki_en=False, news_query="sérum peptides"),
    dict(name="bakuchiol", category=BEAUTE, wiki_fr=None, wiki_en="Bakuchiol", news_query="bakuchiol"),
    dict(name="niacinamide", category=BEAUTE, wiki_fr="Nicotinamide", wiki_en="Niacinamide", news_query="niacinamide"),
    dict(name="ceramides", category=BEAUTE, wiki_fr="Céramide", wiki_en="Ceramide", news_query="céramides soin peau"),
    dict(name="PDRN", category=BEAUTE, wiki_fr=False, wiki_en=False, news_query="PDRN polynucléotides soin"),
    # Boissons et bien-être
    dict(name="matcha", category=BOISSONS, wiki_fr="Matcha", wiki_en="Matcha", news_query="matcha"),
    dict(name="hojicha", category=BOISSONS, wiki_fr=None, wiki_en="Hōjicha", news_query="hojicha"),
    dict(name="kombucha", category=BOISSONS, wiki_fr="Kombucha", wiki_en="Kombucha", news_query="kombucha"),
    dict(name="adaptogènes", category=BOISSONS, wiki_fr="Adaptogène", wiki_en="Adaptogen", news_query="adaptogènes"),
]

# ---------------------------------------------------------------- paramètres du score
W_EVOLUTION, W_RECURRENCE, W_DIFFUSION = 0.4, 0.3, 0.3
UA = "Mozilla/5.0 (compatible; TrendScoutHackathon/0.1)"


# ---------------------------------------------------------------- utilitaires
def slug(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def month_of(d) -> date:
    return date(d.year, d.month, 1)


def parse_period(text: str) -> date | None:
    m = re.match(r"(\d{4})-(\d{2})", text.strip())
    return date(int(m.group(1)), int(m.group(2)), 1) if m else None


def http_get(url: str, timeout: int = 30, retries: int = 5) -> bytes:
    last = None
    for attempt in range(retries + 1):
        wait = 1.5 * (attempt + 1)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            if e.code == 429:  # trop de requêtes : on attend plus longtemps
                retry_after = e.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else 10 * (attempt + 1)
            last = e
        except Exception as e:  # réseau, timeout
            last = e
        if attempt < retries:
            time.sleep(wait)
    raise last


# ---------------------------------------------------------------- source : Wikipedia
def wiki_title(lang: str, hint, query: str) -> str | None:
    if hint is False:
        return None
    base = f"https://{lang}.wikipedia.org/w/api.php?"
    if hint:
        data = json.loads(http_get(base + urllib.parse.urlencode(
            {"action": "query", "titles": hint, "redirects": 1, "format": "json"})))
        page = next(iter(data["query"]["pages"].values()))
        if "missing" not in page:
            return page["title"]
    data = json.loads(http_get(base + urllib.parse.urlencode(
        {"action": "opensearch", "search": query, "limit": 1, "format": "json"})))
    return data[1][0] if data[1] else None


def wiki_monthly(lang: str, title: str, start: date, end: date) -> dict[date, float]:
    art = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           f"{lang}.wikipedia/all-access/user/{art}/monthly/{start:%Y%m%d}/{end:%Y%m%d}")
    try:
        data = json.loads(http_get(url))
    except urllib.error.HTTPError:
        return {}
    out = {}
    for it in data.get("items", []):
        p = date(int(it["timestamp"][:4]), int(it["timestamp"][4:6]), 1)
        if p < month_of(date.today()):  # le mois en cours est incomplet
            out[p] = float(it["views"])
    return out


def collect_wikipedia(kw: dict, sleep: float):
    total: dict[date, float] = {}
    titles = []
    end, start = month_of(date.today()), date(date.today().year - 5, date.today().month, 1)
    for lang, key in (("fr", "wiki_fr"), ("en", "wiki_en")):
        title = wiki_title(lang, kw.get(key), kw["name"])
        time.sleep(sleep)
        if not title:
            continue
        series = wiki_monthly(lang, title, start, end)
        time.sleep(sleep)
        if series:
            titles.append(f"{lang}:{title}")
            for p, v in series.items():
                total[p] = total.get(p, 0.0) + v
    return total, titles


# ---------------------------------------------------------------- source : Google News RSS
def news_items(query: str, window: str) -> list[tuple[datetime, str]]:
    q = urllib.parse.quote(f"{query} when:{window}")
    xml = http_get(f"https://news.google.com/rss/search?q={q}&hl=fr&gl=FR&ceid=FR:fr")
    root = ET.fromstring(xml)
    items = []
    for it in root.iter("item"):
        pub = it.findtext("pubDate")
        src = it.findtext("source") or ""
        if pub:
            items.append((parsedate_to_datetime(pub), src.strip()))
    return items


def collect_news(kw: dict, sleep: float) -> dict:
    q = kw.get("news_query") or kw["name"]
    recent = news_items(q, "30d")
    time.sleep(sleep)
    year = news_items(q, "365d")
    return dict(articles_30d=len(recent), publishers_30d=len({s for _, s in recent if s}),
                articles_365d=len(year), capped=len(year) >= 100)


# ---------------------------------------------------------------- source : Google Trends
def read_gt_csvs(patterns: list[str]) -> dict[str, dict[date, float]]:
    """Retourne {mot-clé normalisé: {mois: valeur}} à partir d'exports Google Trends."""
    out: dict[str, dict[date, float]] = {}
    for pattern in patterns:
        for path in glob.glob(pattern):
            rows = list(csv.reader(open(path, encoding="utf-8-sig")))
            hi = next((i for i, r in enumerate(rows)
                       if r and r[0].strip().lower() in ("time", "semaine", "mois", "date", "week", "month")), None)
            if hi is None:
                continue
            names = [re.sub(r":.*$", "", c).strip().lower() for c in rows[hi][1:]]
            for r in rows[hi + 1:]:
                if not r or not r[0]:
                    continue
                d = parse_period(r[0])
                if not d:
                    continue
                for name, cell in zip(names, r[1:]):
                    cell = cell.strip().replace("<1", "0.5")
                    if cell:
                        bucket = out.setdefault(slug(name), {})
                        bucket.setdefault(d, []).append(float(cell))
    return {k: {d: sum(v) / len(v) for d, v in b.items()} for k, b in out.items()}


def collect_pytrends(name: str) -> dict[date, float]:
    from pytrends.request import TrendReq  # dépendance optionnelle
    pt = TrendReq(hl="fr-FR", tz=60)
    df = None
    for attempt in range(4):  # Google refuse (429) si on va trop vite : on attend de plus en plus longtemps
        try:
            pt.build_payload([name], timeframe="today 5-y", geo="FR")
            df = pt.interest_over_time()
            break
        except Exception as e:
            if "429" not in str(e) or attempt == 3:
                raise
            wait = 40 * (attempt + 1)
            print(f"   Google Trends demande de ralentir, nouvelle tentative dans {wait} s...")
            time.sleep(wait)
    if df is None or df.empty:
        return {}
    monthly: dict[date, list[float]] = {}
    for ts, val in df[name].items():
        monthly.setdefault(month_of(ts.date()), []).append(float(val))
    return {p: sum(v) / len(v) for p, v in monthly.items()}


def read_manual(path: str) -> dict[tuple[str, str], dict[date, float]]:
    out: dict[tuple[str, str], dict[date, float]] = {}
    p = Path(path)
    if not p.exists():
        return out
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        d = parse_period(r.get("period", ""))
        if d and r.get("value", "").strip():
            out.setdefault((slug(r["keyword"]), r["source"].strip().lower()), {})[d] = float(r["value"])
    return out


# ---------------------------------------------------------------- métriques et score
def normalize(series: dict[date, float]) -> dict[date, float] | None:
    m = max(series.values(), default=0)
    return {p: 100 * v / m for p, v in series.items()} if m > 0 else None


def metrics(sn: dict[date, float]) -> dict | None:
    vals = [sn[p] for p in sorted(sn)]
    if len(vals) < 15:
        return None
    first3, last3, prev3 = (statistics.mean(vals[:3]), statistics.mean(vals[-3:]),
                            statistics.mean(vals[-15:-12]))
    last24 = vals[-24:]
    share = sum(v >= 40 for v in last24) / len(last24)
    return dict(
        growth_5y=(last3 - first3) / max(first3, 5) * 100,
        growth_12m=(last3 - prev3) / max(prev3, 5) * 100,
        recurrence=100 * (0.5 * share + 0.5 * min(1.0, last3 / max(vals))),
        last3=last3,
        peak_period=max(sn, key=sn.get),
        points=len(vals),
    )


def stage_of(m: dict | None, g: float | None) -> str:
    """Stade selon la croissance moyenne sur 12 mois (g) et la distance au pic (ratio)."""
    if not m or g is None:
        return "inconnu"
    ratio = m["last3"] / 100  # niveau actuel / pic
    if g >= 50:  # forte croissance récente : tendance installée ou nouvelle vague après un ancien pic
        return "croissance" if ratio >= 0.7 else "émergente"
    if g <= -20:
        return "déclin"
    if ratio < 0.5:  # loin du pic : remonte-t-elle ou continue-t-elle de s'éteindre ?
        return "émergente" if g >= 20 else "déclin"
    return "plateau"


def recommendation(score: float, stage: str, category: str, confidence: str) -> str:
    if score >= 75 and stage in ("croissance", "émergente"):
        text = f"Opportunité forte pour le {MARCHES[category]}"
    elif score >= 50:
        text = "À surveiller : signal prometteur, à confirmer avec d'autres sources"
    else:
        text = "Signal faible : pas de lancement de produit pour l'instant"
    return text + (" (confiance basse)" if confidence == "basse" else "")


# ---------------------------------------------------------------- programme principal
def load_keywords(path: str | None, only: str | None) -> list[dict]:
    kws = KEYWORDS
    if path:
        kws = []
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            kws.append(dict(name=r["name"], category=r.get("category") or SAVEURS,
                            wiki_fr=r.get("wiki_fr") or None, wiki_en=r.get("wiki_en") or None,
                            news_query=r.get("news_query") or r["name"]))
    if only:
        wanted = {slug(x) for x in only.split(",")}
        kws = [k for k in kws if slug(k["name"]) in wanted]
    return kws


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keywords-file")
    ap.add_argument("--only", help="liste de mots-clés séparés par des virgules")
    ap.add_argument("--gt-csv", action="append", default=None, help="export(s) Google Trends (glob accepté)")
    ap.add_argument("--manual", default="signaux_manuels.csv")
    ap.add_argument("--pytrends", action="store_true", help="essayer pytrends pour les mots-clés sans CSV")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--sleep", type=float, default=1.0, help="pause entre requêtes (secondes)")
    args = ap.parse_args()

    kws = load_keywords(args.keywords_file, args.only)
    if not kws:
        sys.exit("Aucun mot-clé à traiter.")
    gt = read_gt_csvs(args.gt_csv or ["time_series_*.csv"])
    manual = read_manual(args.manual)
    today = date.today().isoformat()
    ts_rows, summary = [], []

    for i, kw in enumerate(kws, 1):
        name, sid = kw["name"], slug(kw["name"])
        print(f"[{i}/{len(kws)}] {name}")
        series: dict[str, dict[date, float]] = {}
        wiki_titles, news = [], None

        if sid in gt:
            series["google_trends"] = gt[sid]
        elif args.pytrends:
            try:
                s = collect_pytrends(name)
                if s:
                    series["google_trends"] = s
                time.sleep(8)
            except Exception as e:
                print(f"   google_trends (pytrends) indisponible : {e}")
        for (k, src), s in manual.items():
            if k == sid:
                series[src] = s
        try:
            s, wiki_titles = collect_wikipedia(kw, args.sleep)
            if s:
                series["wikipedia"] = s
        except Exception as e:
            print(f"   wikipedia indisponible : {e}")
        try:
            news = collect_news(kw, args.sleep)
        except Exception as e:
            print(f"   google_news indisponible : {e}")
        time.sleep(args.sleep)

        mets, norm_by_src = {}, {}
        for src, s in series.items():
            sn = normalize(s)
            if not sn:
                continue
            norm_by_src[src] = sn
            for p in sorted(s):
                ts_rows.append(dict(trend_id=sid, trend_name=name, category=kw["category"], source=src,
                                    period=p.isoformat(), value=round(s[p], 2), value_norm=round(sn[p], 1)))
            m = metrics(sn)
            if m:
                mets[src] = m

        # Série de référence : Google Trends, sinon Wikipedia, sinon un signal manuel
        primary = next((mets[s] for s in ("google_trends", "wikipedia") if s in mets),
                       next(iter(mets.values()), None))
        growths = [m["growth_12m"] for m in mets.values()]
        g12 = statistics.mean(growths) if growths else None
        def scaled(g):  # 0 % -> 0, +2000 % ou plus -> 100
            return min(1.0, math.log10(1 + max(g, 0) / 100) / math.log10(21))
        # Évolution = moyenne de la croissance sur 12 mois (récent) et sur 5 ans (de fond)
        evolution = 100 * (0.5 * scaled(g12) + 0.5 * scaled(primary["growth_5y"])) if g12 is not None and primary else 0
        recurrence = statistics.mean(m["recurrence"] for m in mets.values()) if mets else 0
        frac = (sum(g >= 20 for g in growths) / len(growths)) if growths else 0
        pub_part = min(1.0, news["publishers_30d"] / 15) if news else None
        diffusion = 100 * (0.6 * frac + 0.4 * pub_part) if pub_part is not None else 100 * frac
        score = round(W_EVOLUTION * evolution + W_RECURRENCE * recurrence + W_DIFFUSION * diffusion)

        sources = sorted(norm_by_src) + (["google_news"] if news and news["articles_365d"] > 0 else [])
        confidence = "élevée" if len(sources) >= 3 else "moyenne" if len(sources) == 2 else "basse"
        stage = stage_of(primary, g12)
        early = [statistics.mean(sorted(sn.items())[j][1] for j in range(-3, 0))
                 for src, sn in norm_by_src.items() if src in ("tiktok", "pinterest") and len(sn) >= 3]
        summary.append(dict(
            trend_id=sid, trend_name=name, category=kw["category"], score=score,
            growth_5y=round(primary["growth_5y"]) if primary else "",
            growth_12m=round(g12) if g12 is not None else "",
            evolution_score=round(evolution), recurrence_score=round(recurrence),
            diffusion_score=round(diffusion),
            early_signal_score=round(statistics.mean(early)) if early else "",
            stage=stage, confidence=confidence,
            sources=";".join(sources), n_sources=len(sources),
            news_articles_30d=news["articles_30d"] if news else "",
            news_publishers_30d=news["publishers_30d"] if news else "",
            news_articles_365d=news["articles_365d"] if news else "",
            peak_period=primary["peak_period"].isoformat() if primary else "",
            data_points=primary["points"] if primary else 0,
            wiki_articles=";".join(wiki_titles),
            recommendation=recommendation(score, stage, kw["category"], confidence),
            collected_at=today,
        ))
        print(f"   score={score} stade={stage} sources={','.join(sources) or 'aucune'}")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for fname, rows in (("trends_timeseries.csv", ts_rows), ("trends_summary.csv", summary)):
        if rows:
            with open(out / fname, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
    print(f"\nÉcrit : {out / 'trends_summary.csv'} ({len(summary)} tendances), "
          f"{out / 'trends_timeseries.csv'} ({len(ts_rows)} lignes)")


if __name__ == "__main__":
    main()
