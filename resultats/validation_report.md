# Validation du score — 28 cas, score calculé en 2023-11

Durable = niveau moyen entre 2024-11 et 2025-10 >= 50% du pic des 5 années précédant le score. 15 cas durables, 13 non durables.

| Métrique | Méthode naïve (niveau actuel / pic) | V1 (origine) | V2 (corrigée) |
|---|---|---|---|
| AUC (0,5 = hasard, 1 = parfait) | 0.90 | 0.84 | 0.90 |
| Spearman score / résultat réel | 0.82 | 0.59 | 0.68 |
| Exactitude, seuil 50 | — | 71% | 46% |
| Exactitude, seuil 35 | — | 71% | 79% |

## Détail

| Tendance | Score V1 | Score V2 | Niveau 1-2 ans après / pic passé | Durable |
|---|---|---|---|---|
| sriracha | 81 | 60 | 0.38 | non |
| cold brew | 74 | 53 | 0.79 | oui |
| yuzu | 69 | 48 | 0.50 | oui |
| ashwagandha | 67 | 46 | 0.83 | oui |
| birria | 66 | 45 | 0.58 | oui |
| gochujang | 64 | 43 | 0.85 | oui |
| tahini | 64 | 43 | 1.03 | oui |
| hojicha | 63 | 42 | 1.31 | oui |
| matcha | 62 | 41 | 1.49 | oui |
| kombucha | 59 | 38 | 0.71 | oui |
| oat milk | 37 | 37 | 0.60 | oui |
| bakuchiol | 31 | 31 | 0.63 | oui |
| bave d'escargot | 52 | 31 | 0.34 | non |
| niacinamide | 28 | 28 | 0.77 | oui |
| pumpkin spice latte | 48 | 27 | 12.59 | oui |
| adaptogènes | 27 | 27 | 0.82 | oui |
| ambroxan | 27 | 27 | 0.61 | oui |
| acide hyaluronique | 25 | 25 | 0.43 | non |
| golden milk | 24 | 24 | 0.42 | non |
| jackfruit | 24 | 24 | 0.38 | non |
| bubble tea | 41 | 20 | 0.12 | non |
| celery juice | 38 | 17 | 0.16 | non |
| hard seltzer | 15 | 15 | 0.24 | non |
| oud | 8 | 8 | 0.28 | non |
| unicorn frappuccino | 3 | 3 | 0.27 | non |
| aquafaba | 3 | 3 | 0.24 | non |
| cannabidiol | 2 | 2 | 0.12 | non |
| dalgona coffee | 1 | 1 | 0.02 | non |

## Lecture

- La V2 classe bien mieux que le hasard les tendances qui ont tenu (AUC ci-dessus), et mieux que la V1.
- Mais elle ne fait pas mieux que la méthode naïve « niveau actuel / pic » : sur ces données, le score résume surtout où en est la tendance par rapport à son pic. Il n'apporte pas encore d'information prédictive supplémentaire.
- Le seuil de décision 35 a été choisi sur ces mêmes 28 cas : il doit être confirmé sur d'autres cas.
- Première définition (niveau à 80 % du niveau actuel) : AUC 0,44 (V1) et 0,53 (V2). Elle comptait les modes déjà mortes comme durables ; d'où la définition corrigée, fixée avant le calcul (seuil 50 %).

## Limites

- Une seule source historique (Wikipedia) : Google News n'existe pas dans le passé, Google Trends demanderait un export par mot-clé.
- Le trafic global de Wikipedia baisse doucement depuis quelques années, ce qui tire la persistance vers le bas pour tous les cas.
- Les pages vues mesurent la curiosité du public, pas les ventes ni les lancements produits.
- 30 cas choisis à la main : l'échantillon peut être biaisé (tendances déjà connues).
