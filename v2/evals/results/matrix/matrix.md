# Backend matrix

| task | backend | result mean (per run) | LLM calls | text tokens | image tokens | output tokens | wall | cost/run | cost/step |
|---|---|---|---|---|---|---|---|---|---|
| challenge | ax | **13.3**/15 (13, 13, 14) | 32 | 118,478 | 0 (0 imgs) | 3,520 | 64s | $0.136 | 0.43¢ |
| challenge | hybrid | **15.0**/15 (15, 15, 15) | 33 | 124,013 | 45,500 (33 imgs) | 3,600 | 82s | $0.188 | 0.56¢ |
| challenge | hybrid_on_stuck | **12.7**/15 (15, 10, 13) | 31 | 114,889 | 10,920 (8 imgs) | 3,276 | 61s | $0.142 | 0.46¢ |
| sweep | ax | **5.3**/21 (5, 6, 5) | 388 | 1,195,296 | 0 (0 imgs) | 39,613 | 1219s | $1.393 | 0.36¢ |
| sweep | hybrid | **3.3**/21 (4, 3, 3) | 402 | 1,232,036 | 548,275 (402 imgs) | 41,737 | 1336s | $1.989 | 0.50¢ |
| sweep | hybrid_on_stuck | **5.0**/21 (5, 5, 5) | 392 | 1,194,828 | 261,625 (192 imgs) | 40,520 | 1273s | $1.659 | 0.42¢ |
