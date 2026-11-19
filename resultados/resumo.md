# Resumo dos resultados

Média entre as sementes. Acerto = tokens de prompt reaproveitados / tokens de prompt.
Quase acerto = tokens que casaram em nós-fantasma (estavam no cache, saíram e voltaram).

## Few-shot

Conjunto de trabalho médio: 511,631 tokens. Acerto com memória infinita: 92.9%.

| Capacidade | LRU, folha inteira (SGLang) | LRU, cauda por token | Rodízio de cauda (estilo RR-Evict) | Fantasmas, folha inteira (proposta) | Fantasmas, cauda por token (proposta) |
|---:|---:|---:|---:|---:|---:|
| 1% | 36.3% | 40.1% | 41.0% | 42.7% | 46.0% |
| 2% | 54.8% | 56.2% | 58.3% | 57.3% | 58.9% |
| 5% | 76.7% | 77.3% | 82.5% | 77.0% | 77.6% |
| 10% | 88.7% | 88.9% | 92.8% | 92.3% | 92.4% |
| 20% | 92.7% | 92.7% | 92.9% | 92.8% | 92.8% |
| 50% | 92.9% | 92.9% | 92.9% | 92.9% | 92.9% |
| 100% | 92.9% | 92.9% | 92.9% | 92.9% | 92.9% |

Quase acertos com fantasmas (folha inteira): 1%: 11.2%, 2%: 13.5%, 5%: 11.7%, 10%: 0.6%, 20%: 0.1%, 50%: 0.0%, 100%: 0.0%

Orçamento de fantasmas (capacidade 5%), ganho sobre LRU folha inteira:

- Fantasmas, folha inteira (proposta): 0×: +0.00 p.p., 0.25×: +2.80 p.p., 0.5×: +1.53 p.p., 1×: +0.24 p.p., 2×: +0.05 p.p., 4×: +0.06 p.p.
- Fantasmas, cauda por token (proposta): 0×: +0.58 p.p., 0.25×: +3.78 p.p., 0.5×: +2.49 p.p., 1×: +0.89 p.p., 2×: +0.61 p.p., 4×: +0.61 p.p.

## Chat com vários turnos

Conjunto de trabalho médio: 1,230,084 tokens. Acerto com memória infinita: 96.0%.

| Capacidade | LRU, folha inteira (SGLang) | LRU, cauda por token | Rodízio de cauda (estilo RR-Evict) | Fantasmas, folha inteira (proposta) | Fantasmas, cauda por token (proposta) |
|---:|---:|---:|---:|---:|---:|
| 1% | 14.8% | 16.6% | 16.7% | 14.9% | 16.9% |
| 2% | 24.5% | 26.6% | 25.9% | 24.4% | 26.4% |
| 5% | 50.4% | 52.3% | 50.3% | 51.1% | 52.1% |
| 10% | 83.9% | 84.6% | 75.1% | 84.1% | 84.1% |
| 20% | 96.0% | 96.0% | 89.2% | 96.0% | 96.0% |
| 50% | 96.0% | 96.0% | 94.7% | 96.0% | 96.0% |
| 100% | 96.0% | 96.0% | 96.0% | 96.0% | 96.0% |

Quase acertos com fantasmas (folha inteira): 1%: 8.1%, 2%: 16.2%, 5%: 32.0%, 10%: 11.9%, 20%: 0.0%, 50%: 0.0%, 100%: 0.0%

Orçamento de fantasmas (capacidade 5%), ganho sobre LRU folha inteira:

- Fantasmas, folha inteira (proposta): 0×: +0.00 p.p., 0.25×: -1.91 p.p., 0.5×: -0.15 p.p., 1×: +0.63 p.p., 2×: +1.63 p.p., 4×: +1.70 p.p.
- Fantasmas, cauda por token (proposta): 0×: +1.90 p.p., 0.25×: -0.21 p.p., 0.5×: +1.26 p.p., 1×: +1.70 p.p., 2×: +1.87 p.p., 4×: +1.87 p.p.
