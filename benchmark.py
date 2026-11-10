"""Benchmark des LLM Ollama sur le pipeline RAG du projet.

Usage :
    python ingest.py          # la base doit être chargée
    python benchmark.py       # écrit benchmark_results.json
    python make_pdf.py        # génère benchmark_llm.pdf
"""

import json
import re
import time
import unicodedata

import api
import config
import rag

MODELS = ["qwen3.5:4b", "llama3.2:3b", "gemma3:4b"]

# (question, [groupes de mots-clés : chaque groupe doit être trouvé], type)
QUESTIONS = [
    ("Comment s'appelle le cheval de Léo ?", [["eclair"]], "fait"),
    ("De quelle couleur est le cheval de Léo ?", [["blanc"]], "fait"),
    ("Qu'y a-t-il dans le sac à dos de Léo ?", [["gourde", "eau"], ["pomme"], ["carnet"], ["loupe"]], "liste"),
    ("Qui est le méchant de l'histoire ?", [["baron", "grognon"]], "fait"),
    ("Que fait la machine du Baron Grognon ?", [["fleur"], ["aspir"]], "fait"),
    ("Combien d'écureuils attaquent la machine ?", [["vingt", "20"]], "fait"),
    ("Comment Léo arrête-t-il la machine à vapeur ?", [["ecureuil"], ["gland"]], "raisonnement"),
    ("Que donne Léo au Baron à la fin ?", [["pomme"]], "fait"),
    ("Quel est le prénom de la mère de Léo ?", [["precise", "ne dit pas", "ne parle pas", "ne sait pas", "pas dit", "pas mention"]], "hors-sujet"),
    ("Quel âge a Léo ?", [["precise", "ne dit pas", "ne parle pas", "ne sait pas", "pas dit", "pas mention"]], "hors-sujet"),
]


REFUS = ["precise", "ne dit pas", "ne parle pas", "ne sait pas", "pas dit", "pas mention",
         "indication", "indique pas", "trouve pas"]
QUESTIONS = [(q, [REFUS] if kind == "hors-sujet" else g, kind) for q, g, kind in QUESTIONS]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def score(answer: str, groups: list[list[str]]) -> float:
    a = norm(answer)
    found = sum(1 for g in groups if any(k in a for k in g))
    return found / len(groups)


def main() -> None:
    results = []
    # Retrieval fait une seule fois par question (identique pour tous les modèles)
    contexts = {}
    for q, _, _ in QUESTIONS:
        t0 = time.perf_counter()
        sources = api.retrieve(q, config.TOP_K)
        contexts[q] = (sources, time.perf_counter() - t0)

    for model in MODELS:
        print(f"\n=== {model} ===")
        # Préchauffage : charge le modèle en mémoire (non compté dans les temps)
        rag._ollama.chat(model=model, messages=[{"role": "user", "content": "Bonjour"}],
                         options={"num_predict": 1})
        for q, groups, kind in QUESTIONS:
            sources, _ = contexts[q]
            context = "\n\n---\n\n".join(f"[{s.chapter}]\n{s.text}" for s in sources)
            messages = [
                {"role": "system", "content": api.SYSTEM_PROMPT},
                {"role": "user", "content": f"Extraits de l'histoire :\n\n{context}\n\nQuestion : {q}"},
            ]
            t0 = time.perf_counter()
            r = rag._ollama.chat(model=model, messages=messages, think=False,
                                 options={"temperature": 0.2})
            elapsed = time.perf_counter() - t0
            answer = r["message"]["content"].strip()
            tokens = r.get("eval_count") or 0
            eval_s = (r.get("eval_duration") or 0) / 1e9
            s = score(answer, groups)
            results.append({
                "model": model, "question": q, "kind": kind, "answer": answer,
                "score": s, "seconds": round(elapsed, 2), "tokens": tokens,
                "tok_per_s": round(tokens / eval_s, 1) if eval_s else None,
            })
            print(f"[{s:.2f}] {elapsed:5.1f}s  {q}\n      -> {answer[:140]!r}")

    with open("benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nRésultats écrits dans benchmark_results.json")


if __name__ == "__main__":
    main()
