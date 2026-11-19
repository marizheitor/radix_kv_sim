# Resumo dos resultados

Média entre as sementes. Acerto = tokens de prompt reaproveitados / tokens de prompt.
Quase acerto = tokens que casaram em nós-fantasma (estavam no cache, saíram e voltaram).

## Few-shot

Conjunto de trabalho médio: 516,450 tokens. Acerto com memória infinita: 92.7%.

| Capacidade | LRU, folha inteira (SGLang) | LRU, cauda por token | Rodízio de cauda (estilo RR-Evict) | Fantasmas, folha inteira (proposta) | Fantasmas, cauda por token (proposta) |
|---:|---:|---:|---:|---:|---:|
| 1% | 36.5% | 40.5% | 41.1% | 42.9% | 46.1% |
| 2% | 55.0% | 56.3% | 58.3% | 57.3% | 59.1% |
| 5% | 76.1% | 76.7% | 82.3% | 76.5% | 77.3% |
| 10% | 88.7% | 88.8% | 92.6% | 91.5% | 91.8% |
| 20% | 92.5% | 92.5% | 92.7% | 92.6% | 92.6% |
| 50% | 92.7% | 92.7% | 92.7% | 92.7% | 92.7% |
| 100% | 92.7% | 92.7% | 92.7% | 92.7% | 92.7% |

Quase acertos com fantasmas (folha inteira): 1%: 11.0%, 2%: 13.3%, 5%: 12.0%, 10%: 1.1%, 20%: 0.1%, 50%: 0.0%, 100%: 0.0%

Orçamento de fantasmas (capacidade 5%), ganho sobre LRU folha inteira:

- Fantasmas, folha inteira (proposta): 0×: +0.00 p.p., 0.25×: +2.55 p.p., 0.5×: +1.76 p.p., 1×: +0.36 p.p., 2×: +0.10 p.p., 4×: +0.08 p.p.
- Fantasmas, cauda por token (proposta): 0×: +0.60 p.p., 0.25×: +4.37 p.p., 0.5×: +2.64 p.p., 1×: +1.19 p.p., 2×: +0.71 p.p., 4×: +0.67 p.p.

## Chat com vários turnos

Conjunto de trabalho médio: 1,222,392 tokens. Acerto com memória infinita: 95.9%.

| Capacidade | LRU, folha inteira (SGLang) | LRU, cauda por token | Rodízio de cauda (estilo RR-Evict) | Fantasmas, folha inteira (proposta) | Fantasmas, cauda por token (proposta) |
|---:|---:|---:|---:|---:|---:|
| 1% | 15.1% | 16.6% | 16.7% | 15.3% | 16.7% |
| 2% | 24.0% | 26.1% | 25.8% | 23.7% | 25.4% |
| 5% | 50.2% | 51.7% | 49.9% | 50.8% | 51.8% |
| 10% | 84.3% | 84.9% | 74.9% | 83.8% | 83.9% |
| 20% | 95.9% | 95.9% | 89.2% | 95.9% | 95.9% |
| 50% | 95.9% | 95.9% | 94.6% | 95.9% | 95.9% |
| 100% | 95.9% | 95.9% | 95.9% | 95.9% | 95.9% |

Quase acertos com fantasmas (folha inteira): 1%: 7.4%, 2%: 16.7%, 5%: 32.4%, 10%: 12.0%, 20%: 0.0%, 50%: 0.0%, 100%: 0.0%

Orçamento de fantasmas (capacidade 5%), ganho sobre LRU folha inteira:

- Fantasmas, folha inteira (proposta): 0×: +0.00 p.p., 0.25×: -1.10 p.p., 0.5×: -0.17 p.p., 1×: +0.52 p.p., 2×: +1.00 p.p., 4×: +1.28 p.p.
- Fantasmas, cauda por token (proposta): 0×: +1.47 p.p., 0.25×: +1.31 p.p., 0.5×: +1.27 p.p., 1×: +1.55 p.p., 2×: +1.35 p.p., 4×: +1.41 p.p.
