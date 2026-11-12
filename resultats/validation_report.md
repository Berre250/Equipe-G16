# Validation du score — 28 cas, score calculé en 2023-11

Durable = niveau moyen entre 2024-11 et 2025-10 >= 80% du niveau au moment du score. 20 cas durables, 8 non durables.

| Métrique | V1 (origine) | V2 (corrigée) |
|---|---|---|
| AUC (0,5 = hasard) | 0.44 | 0.53 |
| Spearman score / persistance | -0.15 | -0.08 |
| Exactitude (score >= 50) | 46% | 29% |

## Détail

| Tendance | Score V1 | Score V2 | Persistance | Durable |
|---|---|---|---|---|
| sriracha | 81 | 60 | 0.42 | non |
| cold brew | 74 | 53 | 0.96 | oui |
| yuzu | 69 | 48 | 0.69 | non |
| ashwagandha | 67 | 46 | 0.88 | oui |
| birria | 66 | 45 | 0.95 | oui |
| gochujang | 64 | 43 | 0.99 | oui |
| tahini | 64 | 43 | 1.13 | oui |
| hojicha | 63 | 42 | 1.42 | oui |
| matcha | 62 | 41 | 1.75 | oui |
| kombucha | 59 | 38 | 0.90 | oui |
| oat milk | 37 | 37 | 0.84 | oui |
| bakuchiol | 31 | 31 | 0.98 | oui |
| bave d'escargot | 52 | 31 | 0.54 | non |
| niacinamide | 28 | 28 | 1.00 | oui |
| pumpkin spice latte | 48 | 27 | 20.19 | oui |
| adaptogènes | 27 | 27 | 1.11 | oui |
| ambroxan | 27 | 27 | 1.03 | oui |
| acide hyaluronique | 25 | 25 | 0.62 | non |
| golden milk | 24 | 24 | 0.80 | oui |
| jackfruit | 24 | 24 | 0.66 | non |
| bubble tea | 41 | 20 | 0.48 | non |
| celery juice | 38 | 17 | 0.62 | non |
| hard seltzer | 15 | 15 | 0.61 | non |
| oud | 8 | 8 | 0.90 | oui |
| unicorn frappuccino | 3 | 3 | 1.59 | oui |
| aquafaba | 3 | 3 | 1.27 | oui |
| cannabidiol | 2 | 2 | 1.07 | oui |
| dalgona coffee | 1 | 1 | 0.99 | oui |

## Limites

- Une seule source historique (Wikipedia) : Google News n'existe pas dans le passé, Google Trends demanderait un export par mot-clé.
- Le trafic global de Wikipedia baisse doucement depuis quelques années, ce qui tire la persistance vers le bas pour tous les cas.
- Les pages vues mesurent la curiosité du public, pas les ventes ni les lancements produits.
- 30 cas choisis à la main : l'échantillon peut être biaisé (tendances déjà connues).
