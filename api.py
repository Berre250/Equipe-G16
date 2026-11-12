"""API de questions/réponses sur les fiches de tendances Givaudan (RAG + Ollama).

Lancement :
    uvicorn api:app --reload
Swagger : http://localhost:8000/docs
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import config
import rag

SYSTEM_PROMPT = """Tu es un analyste de tendances pour l'équipe marketing et consumer insights de Givaudan. Tu réponds à Camille, cheffe de produit marketing.
Règles :
- Réponds UNIQUEMENT à partir des fiches de tendances fournies.
- Si l'information ne se trouve pas dans les fiches, dis-le clairement : « Ce n'est pas dans mes fiches. » N'invente jamais de chiffre, de tendance ni de source.
- Quand tu expliques un score, cite le nom de la tendance et ses sources (Google Trends, Wikipedia, Google News...).
- Le score de durabilité est calculé par la brique Data : ne le recalcule pas et ne le modifie pas. Explique-le avec ses trois critères (évolution, récurrence, diffusion) et le stade de la tendance.
- Signale quand la confiance des données est moyenne ou basse, ou quand la fiche dit que le score est peu fiable.
- Réponds en français, en deux ou trois phrases claires, sans jargon."""

app = FastAPI(
    title="Radar de tendances Givaudan - Assistant (RAG)",
    description="Pose des questions en langage courant sur les tendances suivies par la brique Data "
                "(saveurs, parfumerie, actifs beauté, boissons). Les fiches de tendances sont chargées dans "
                "la base vectorielle ; les réponses sont rédigées par un LLM Ollama à partir des fiches retrouvées.",
    version="1.0.0",
)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["Pourquoi le score du yuzu est-il bas ?"])
    top_k: int = Field(config.TOP_K, ge=1, le=20, description="Nombre de fiches à retrouver")


class Source(BaseModel):
    chapter: str
    text: str
    score: float = Field(description="Similarité cosinus (1 = identique)")


class AskResponse(BaseModel):
    question: str
    answer: str
    model: str
    sources: list[Source]


def retrieve(question: str, top_k: int) -> list[Source]:
    collection = rag.get_collection()
    if collection.count() == 0:
        raise HTTPException(503, "La base est vide : lance d'abord `python ingest.py`.")
    result = collection.query(
        query_embeddings=[rag.embed_query(question)],
        n_results=min(top_k, collection.count()),
    )
    return [
        Source(chapter=meta["chapter"], text=doc, score=round(1 - dist, 4))
        for doc, meta, dist in zip(result["documents"][0], result["metadatas"][0], result["distances"][0])
    ]


@app.get("/health", tags=["système"])
def health():
    """Vérifie que la base est chargée et indique les modèles utilisés."""
    return {
        "chunks": rag.get_collection().count(),
        "llm_model": config.LLM_MODEL,
        "embed_model": config.EMBED_MODEL,
    }


@app.post("/search", response_model=list[Source], tags=["tendances"])
def search(req: AskRequest):
    """Retrouve les fiches de tendances qui correspondent à la demande (sans appeler le LLM)."""
    return retrieve(req.question, req.top_k)


@app.post("/ask", response_model=AskResponse, tags=["tendances"])
def ask(req: AskRequest):
    """Répond à une question sur les tendances à partir des fiches retrouvées."""
    sources = retrieve(req.question, req.top_k)
    context = "\n\n---\n\n".join(f"[{s.chapter}]\n{s.text}" for s in sources)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Fiches de tendances :\n\n{context}\n\nQuestion : {req.question}"},
    ]
    try:
        answer = rag.chat(messages)
    except Exception as exc:  # Ollama injoignable, modèle absent...
        raise HTTPException(502, f"Erreur Ollama : {exc}") from exc
    return AskResponse(question=req.question, answer=answer.strip(), model=config.LLM_MODEL, sources=sources)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
