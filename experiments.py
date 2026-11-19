"""
Roda os experimentos e gera CSVs e gráficos em resultados/.

    python experiments.py            # completo (3 sementes, 3000 pedidos por carga)
    python experiments.py --quick    # rápido, para testar (1 semente, 600 pedidos)

Experimento 1: taxa de acerto x capacidade, para as cinco configurações abaixo.
Experimento 2: efeito do orçamento de fantasmas, numa capacidade fixa.

A capacidade é dada como fração do "conjunto de trabalho": o total de tokens
que a árvore guardaria com memória infinita para aquele trace. O orçamento de
fantasmas é dado como múltiplo da capacidade (em tokens de metadado).
"""

import argparse
import csv
import statistics
import time
from pathlib import Path

from radix_cache import RadixCache
from workloads import WORKLOADS, Corpus, get_encoding

CONFIGS = [  # (id, rótulo, parâmetros do RadixCache)
    ("lru-folha", "LRU, folha inteira (SGLang)", dict(policy="lru", mode="leaf")),
    ("lru-token", "LRU, cauda por token", dict(policy="lru", mode="token")),
    ("rodizio", "Rodízio de cauda (estilo RR-Evict)", dict(policy="rr", rr_chunk=32)),
    ("fantasma-folha", "Fantasmas, folha inteira (proposta)", dict(policy="ghost", mode="leaf")),
    ("fantasma-token", "Fantasmas, cauda por token (proposta)", dict(policy="ghost", mode="token")),
]
FRACS = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]
GHOST_BUDGETS = [0, 0.25, 0.5, 1, 2, 4]
SWEEP_FRAC = 0.05


def run(trace, capacity, **params):
    """Simula o servidor: para cada pedido, mede o acerto do prompt e depois
    insere prompt + resposta (como o SGLang faz ao terminar o pedido)."""
    c = RadixCache(capacity, **params)
    hits = near = total = 0
    t_match = t_insert = 0.0
    node_samples, ghost_samples = [], []
    for k, req in enumerate(trace):
        t0 = time.perf_counter()
        h, g = c.match(req.prompt)
        t1 = time.perf_counter()
        c.insert(req.prompt + req.output)
        t2 = time.perf_counter()
        hits += h
        near += g
        total += len(req.prompt)
        t_match += t1 - t0
        t_insert += t2 - t1
        if k % 20 == 0:
            node_samples.append(c.num_nodes)
            ghost_samples.append(c.num_ghost_nodes)
    n = len(trace)
    return {
        "n_requests": n,
        "hit_rate": hits / total,
        "near_hit_rate": near / total,       # casou em fantasmas: removido e pedido de novo
        "hit_tokens": hits,
        "prompt_tokens": total,
        "final_size": c.size,
        "mean_nodes": statistics.mean(node_samples),
        "mean_ghost_nodes": statistics.mean(ghost_samples),
        "final_ghost_size": c.ghost_size,
        "revived_tokens": c.revived_tokens,
        "evicted_tokens": c.evicted_tokens,
        "evict_ops": c.evict_ops,
        "splits": c.splits,
        # microssegundos por pedido; o tempo de inserção NÃO inclui o de remoção
        "t_match_us": t_match / n * 1e6,
        "t_insert_us": (t_insert - c.t_evict) / n * 1e6,
        "t_evict_us": c.t_evict / n * 1e6,
    }


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--requests", type=int, default=3000)
    ap.add_argument("--corpus", help="pasta com arquivos .txt (padrão: docstrings da stdlib)")
    ap.add_argument("--out", default="resultados")
    args = ap.parse_args()
    if args.quick:
        args.seeds, args.requests = 1, 600

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    enc = get_encoding()
    corpus = Corpus.from_dir(enc, args.corpus) if args.corpus else Corpus.from_stdlib(enc)
    print(f"tokenizador: {enc.name} | corpus: {len(corpus.tokens):,} tokens")

    rows, sweep = [], []
    for wl, gen in WORKLOADS.items():
        for seed in range(args.seeds):
            trace = gen(corpus, seed, n_requests=args.requests)
            ideal = run(trace, float("inf"))
            ws = ideal["final_size"]
            print(f"\n[{wl} | semente {seed}] {len(trace)} pedidos, "
                  f"{ideal['prompt_tokens']:,} tokens de prompt, conjunto de trabalho {ws:,} tokens, "
                  f"acerto com memória infinita {ideal['hit_rate']:.1%}")
            base = {"workload": wl, "seed": seed, "working_set": ws,
                    "ideal_hit_rate": ideal["hit_rate"]}

            for frac in FRACS:
                cap = max(1, int(frac * ws))
                line = f"  cap {frac:>5.0%}:"
                for cid, label, params in CONFIGS:
                    r = run(trace, cap, **params)
                    rows.append({**base, "experiment": "capacidade", "frac": frac, "capacity": cap,
                                 "config": cid, "label": label, "ghost_budget": "", **r})
                    line += f"  {cid} {r['hit_rate']:6.1%}"
                print(line)

            cap = max(1, int(SWEEP_FRAC * ws))
            for gb in GHOST_BUDGETS:
                for cid, mode in (("fantasma-folha", "leaf"), ("fantasma-token", "token")):
                    r = run(trace, cap, policy="ghost", mode=mode, ghost_capacity=int(gb * cap))
                    sweep.append({**base, "experiment": "orcamento", "frac": SWEEP_FRAC,
                                  "capacity": cap, "config": cid, "ghost_budget": gb, **r})
            for cid, mode in (("lru-folha", "leaf"), ("lru-token", "token")):
                r = run(trace, cap, policy="lru", mode=mode)
                sweep.append({**base, "experiment": "orcamento", "frac": SWEEP_FRAC,
                              "capacity": cap, "config": cid, "ghost_budget": "", **r})

    write_csv(rows, out / "resultados_capacidade.csv")
    write_csv(sweep, out / "resultados_orcamento.csv")
    print(f"\nCSVs salvos em {out}/")

    try:
        import plots
        plots.make_all(out)
        print(f"Gráficos salvos em {out}/")
    except ImportError as e:
        print(f"(gráficos não gerados: {e})")


if __name__ == "__main__":
    main()
