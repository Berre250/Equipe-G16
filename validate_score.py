#!/usr/bin/env python3
"""Validation du score de durabilité sur les cas de référence (reference_cases.csv).

Principe : on se place à une date passée (--as-of, par défaut 2023-11). Le score est calculé
UNIQUEMENT avec les données disponibles avant cette date, puis on regarde ce qui s'est réellement
passé ensuite. Une tendance est jugée « durable » si, 12 à 24 mois plus tard, son niveau moyen
reste au moins à --threshold (80 %) de son niveau au moment du score.

Le score est bon s'il classe haut les tendances qui ont duré et bas celles qui sont retombées.
On compare la V1 (formule d'origine) et la V2 (formule corrigée).

Métriques :
  - AUC         : probabilité qu'une tendance durable ait un meilleur score qu'une non durable
                  (0,5 = hasard, 1 = parfait)
  - Spearman    : corrélation de rang entre le score et la persistance réelle (-1 à 1)
  - Exactitude  : part des cas bien classés avec la règle « score >= 50 -> durable »
  - Accord Product : si la colonne `expected` est remplie (durable / passagère)

Données : pages vues Wikipedia (fr + en), seule source gratuite disponible dans le passé.
Les séries téléchargées sont gardées dans resultats/validation_series.json pour pouvoir
relancer le calcul à l'identique (--offline), sans réseau.

Usage :
  python validate_score.py
  python validate_score.py --as-of 2023-11 --threshold 0.8
  python validate_score.py --offline        # réutilise les séries déjà téléchargées
"""

import argparse
import csv
import json
import statistics
import sys
from datetime import date
from pathlib import Path

import collect_trends as ct


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def load_cases(path: str) -> list[dict]:
    cases = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        cases.append(dict(
            name=r["name"], category=r.get("category") or ct.SAVEURS,
            # case vide = ne pas utiliser cette langue (évite les articles ambigus)
            wiki_en=r.get("wiki_en") or False, wiki_fr=r.get("wiki_fr") or False,
            expected=(r.get("expected") or "").strip().lower(), note=r.get("note", "")))
    return cases


# ---------------------------------------------------------------- statistiques (bibliothèque standard)
def ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    try:
        return statistics.correlation(rx, ry)
    except statistics.StatisticsError:
        return None


def auc(scores: list[float], labels: list[bool]) -> float | None:
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def fmt(x, digits=2):
    return "n/a" if x is None else f"{x:.{digits}f}"


# ---------------------------------------------------------------- programme principal
def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)  # progression visible même redirigée
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default="reference_cases.csv")
    ap.add_argument("--as-of", default="2023-11", help="date du score (AAAA-MM)")
    ap.add_argument("--threshold", type=float, default=0.8,
                    help="persistance minimale pour être jugée durable (0,8 = 80 %%)")
    ap.add_argument("--out-dir", default=ct.DEFAULT_OUT_DIR)
    ap.add_argument("--offline", action="store_true", help="réutiliser validation_series.json")
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    as_of = ct.parse_period(args.as_of)
    if not as_of:
        sys.exit("--as-of doit être au format AAAA-MM")
    start = add_months(as_of, -60)                      # 5 ans d'historique avant le score
    after_from, after_to = add_months(as_of, 12), add_months(as_of, 24)   # fenêtre observée ensuite
    if after_to > ct.month_of(date.today()):
        sys.exit(f"--as-of trop récent : il faut 24 mois complets après {as_of:%Y-%m}.")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cache_path = out / "validation_series.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}

    cases = load_cases(args.cases)
    rows = []
    for i, c in enumerate(cases, 1):
        key = ct.slug(c["name"])
        print(f"[{i}/{len(cases)}] {c['name']}")
        if key in cache and (args.offline or cache[key].get("start") == start.isoformat()):
            raw = {date.fromisoformat(p): v for p, v in cache[key]["series"].items()}
            titles = cache[key]["titles"]
        elif args.offline:
            print("   absent du cache, ignoré (--offline)")
            continue
        else:
            try:
                raw, titles = ct.collect_wikipedia(c, args.sleep, start=start, end=after_to)
            except Exception as e:
                print(f"   wikipedia indisponible : {e}")
                continue
            cache[key] = dict(start=start.isoformat(), titles=titles,
                              series={p.isoformat(): v for p, v in sorted(raw.items())})

        before = {p: v for p, v in raw.items() if p < as_of}
        after = [v for p, v in raw.items() if after_from <= p < after_to]
        last3 = [before[p] for p in sorted(before)[-3:]]
        if len(before) < 15 or len(after) < 6 or not last3 or statistics.mean(last3) == 0:
            print(f"   pas assez de données ({len(before)} mois avant, {len(after)} après), ignoré")
            continue

        persistence = statistics.mean(after) / statistics.mean(last3)
        mets, _, primary = ct.series_metrics({"wikipedia": before})
        if not primary:
            print("   métriques impossibles, ignoré")
            continue
        # Pas de Google News dans le passé : news=None, exactement le cas où la V1 surévaluait la diffusion
        v1 = ct.compute_score(mets, primary, None, version="v1")
        v2 = ct.compute_score(mets, primary, None, version="v2")
        rows.append(dict(
            name=c["name"], category=c["category"], wiki_articles=";".join(titles),
            score_v1=v1["score"], score_v2=v2["score"],
            diffusion_v1=round(v1["diffusion"]), diffusion_v2=round(v2["diffusion"]),
            stage=ct.stage_of(primary, v2["g12"]),
            persistence=round(persistence, 3), durable=persistence >= args.threshold,
            expected=c["expected"], note=c["note"]))
        print(f"   V1={v1['score']} V2={v2['score']} persistance={persistence:.2f}")

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    if not rows:
        sys.exit("Aucun cas exploitable : vérifie l'accès à Wikipedia ou relance sans --offline.")

    with open(out / "validation_results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    labels = [r["durable"] for r in rows]
    pers = [r["persistence"] for r in rows]
    report = [f"# Validation du score — {len(rows)} cas, score calculé en {as_of:%Y-%m}",
              "",
              f"Durable = niveau moyen entre {after_from:%Y-%m} et {add_months(after_to, -1):%Y-%m} "
              f">= {args.threshold:.0%} du niveau au moment du score. "
              f"{sum(labels)} cas durables, {len(labels) - sum(labels)} non durables.",
              "",
              "| Métrique | V1 (origine) | V2 (corrigée) |",
              "|---|---|---|"]
    res = {}
    for v in ("v1", "v2"):
        s = [r[f"score_{v}"] for r in rows]
        acc = sum((x >= 50) == l for x, l in zip(s, labels)) / len(rows)
        res[v] = dict(auc=auc(s, labels), rho=spearman(s, pers), acc=acc)
    report += [f"| AUC (0,5 = hasard) | {fmt(res['v1']['auc'])} | {fmt(res['v2']['auc'])} |",
               f"| Spearman score / persistance | {fmt(res['v1']['rho'])} | {fmt(res['v2']['rho'])} |",
               f"| Exactitude (score >= 50) | {res['v1']['acc']:.0%} | {res['v2']['acc']:.0%} |"]
    with_expected = [r for r in rows if r["expected"] in ("durable", "passagère", "passagere")]
    if with_expected:
        agree = sum((r["expected"] == "durable") == r["durable"] for r in with_expected)
        report += ["", f"Accord avec les étiquettes Product : {agree}/{len(with_expected)} cas."]
    report += ["", "## Détail", "",
               "| Tendance | Score V1 | Score V2 | Persistance | Durable |", "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: -r["score_v2"]):
        report.append(f"| {r['name']} | {r['score_v1']} | {r['score_v2']} | "
                      f"{r['persistence']:.2f} | {'oui' if r['durable'] else 'non'} |")
    report += ["", "## Limites", "",
               "- Une seule source historique (Wikipedia) : Google News n'existe pas dans le passé, "
               "Google Trends demanderait un export par mot-clé.",
               "- Le trafic global de Wikipedia baisse doucement depuis quelques années, ce qui tire "
               "la persistance vers le bas pour tous les cas.",
               "- Les pages vues mesurent la curiosité du public, pas les ventes ni les lancements produits.",
               "- 30 cas choisis à la main : l'échantillon peut être biaisé (tendances déjà connues)."]
    (out / "validation_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n" + "\n".join(report[:10]))
    print(f"\nÉcrit : {out / 'validation_results.csv'}, {out / 'validation_report.md'}")


if __name__ == "__main__":
    main()
