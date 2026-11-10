"""Génère benchmark_llm.pdf à partir de benchmark_results.json (scores recalculés)."""

import json
from collections import defaultdict

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from benchmark import QUESTIONS, score

SIZES = {"qwen3.5:4b": "3,3 Go", "llama3.2:3b": "2,0 Go", "gemma3:4b": "3,4 Go"}
GROUPS = {q: g for q, g, _ in QUESTIONS}

results = json.load(open("benchmark_results.json", encoding="utf-8"))
for r in results:
    r["score"] = score(r["answer"], GROUPS[r["question"]])

by_model = defaultdict(list)
for r in results:
    by_model[r["model"]].append(r)

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Title"], fontSize=20)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceBefore=14)
P = ParagraphStyle("P", parent=styles["BodyText"], fontSize=10, leading=14)
SMALL = ParagraphStyle("S", parent=P, fontSize=8, leading=10)


def table(data, widths, header=True):
    t = Table(data, colWidths=widths, repeatRows=1)
    st = [("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("FONTSIZE", (0, 0), (-1, -1), 8)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b4a7a")),
               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    t.setStyle(TableStyle(st))
    return t


def avg(l, k):
    v = [x[k] for x in l if x[k] is not None]
    return sum(v) / len(v)


story = [Paragraph("Benchmark des modèles Ollama", H1),
         Paragraph("Équipe G16 - Story RAG API (histoire de Léo et Éclair)", styles["Heading3"])]

story += [Paragraph("1. Contexte et méthode", H2), Paragraph(
    "Le projet répond à des questions d'enfants sur une histoire (<b>story.txt</b>) : les passages "
    "pertinents sont retrouvés dans ChromaDB (embeddings <b>nomic-embed-text</b>), puis un LLM Ollama "
    "rédige la réponse avec le prompt système de <b>api.py</b>. Seul le LLM change entre les tests ; "
    "la recherche, le prompt et la température (0,2) sont identiques.", P), Spacer(1, 6), Paragraph(
    "<b>10 questions</b> : 8 dont la réponse est dans l'histoire (faits, liste, raisonnement) et 2 "
    "pièges dont la réponse n'y est pas (le bon comportement est de dire que l'histoire ne le précise "
    "pas). Un score automatique par mots-clés est calculé, puis les réponses ont été relues. "
    "Machine de test : Windows 11, 15 Go de RAM, <b>CPU seul (pas de GPU)</b>. Le mode "
    "« réflexion » des modèles a été désactivé (réponse directe).", P)]

story += [Paragraph("2. Résultats", H2)]
rows = [["Modèle", "Taille disque", "Réponses justes", "Temps moyen / réponse", "Vitesse (tokens/s)"]]
for m, l in by_model.items():
    rows.append([m, SIZES[m], f"{avg(l, 'score') * 100:.0f} %", f"{avg(l, 'seconds'):.1f} s",
                 f"{avg(l, 'tok_per_s'):.1f}"])
story += [table(rows, [3.5 * cm, 3 * cm, 3.5 * cm, 4 * cm, 3.5 * cm]), Spacer(1, 8)]

story += [Paragraph("Score par question (1 = correct, 0,5 = partiel)", P)]
rows = [["Question", "Type"] + list(by_model)]
for q, _, kind in QUESTIONS:
    rows.append([Paragraph(q, SMALL), kind] + [f"{next(x for x in l if x['question'] == q)['score']:.1f}"
                                               for l in by_model.values()])
story += [table(rows, [7 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm])]

story += [Paragraph("3. Analyse", H2)]
for m, l in by_model.items():
    miss = [x for x in l if x["score"] < 1]
    txt = f"<b>{m}</b> : {avg(l, 'score') * 100:.0f} % de réponses justes, {avg(l, 'seconds'):.1f} s en moyenne."
    for x in miss:
        txt += (f" Réponse partielle à « {x['question']} » : {x['answer'][:160]}")
    story.append(Paragraph(txt, P))
    story.append(Spacer(1, 4))

story += [Paragraph("4. Limites", H2), Paragraph(
    "Seulement 10 questions sur une histoire courte (11 morceaux) : les écarts de qualité sont faibles "
    "et ne sont pas statistiquement significatifs. Les temps dépendent du processeur (pas de GPU) et "
    "incluent la lecture des passages par le modèle. Le modèle par défaut du dépôt, qwen2.5:1.5b, n'a pas "
    "été testé ici.", P)]

best = max(by_model, key=lambda m: (avg(by_model[m], "score"), -avg(by_model[m], "seconds")))
story += [Paragraph("5. Conclusion", H2), Paragraph(
    f"Pour cette mission, <b>{best}</b> est le meilleur compromis dans nos tests : il obtient le meilleur "
    "score et reste parmi les plus rapides, et il refuse correctement de répondre quand l'histoire ne le "
    "précise pas. <b>gemma3:4b</b> est aussi fiable mais un peu plus lent. <b>llama3.2:3b</b> est le plus "
    "léger (2,0 Go) mais oublie des éléments dans les réponses de raisonnement. Tous restent lents sur "
    "CPU : un GPU ou un modèle plus petit améliorerait nettement le temps de réponse.", P)]

SimpleDocTemplate("benchmark_llm.pdf", pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                  topMargin=2 * cm, bottomMargin=2 * cm, title="Benchmark LLM - Equipe G16").build(story)
print("benchmark_llm.pdf généré")
for m, l in by_model.items():
    print(m, f"{avg(l, 'score') * 100:.0f}%", f"{avg(l, 'seconds'):.1f}s")
