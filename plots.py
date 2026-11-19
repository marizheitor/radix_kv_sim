"""
Gera os gráficos e um resumo em tabela a partir dos CSVs de resultados/.

    python plots.py                 # usa a pasta resultados/
    python plots.py --out outra_pasta
"""

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CONFIG_ORDER = ["lru-folha", "lru-token", "rodizio", "fantasma-folha", "fantasma-token"]
LABELS = {
    "lru-folha": "LRU, folha inteira (SGLang)",
    "lru-token": "LRU, cauda por token",
    "rodizio": "Rodízio de cauda (estilo RR-Evict)",
    "fantasma-folha": "Fantasmas, folha inteira (proposta)",
    "fantasma-token": "Fantasmas, cauda por token (proposta)",
}
SHORT = {"lru-folha": "LRU\nfolha", "lru-token": "LRU\ncauda", "rodizio": "Rodízio\nde cauda",
         "fantasma-folha": "Fantasmas\nfolha", "fantasma-token": "Fantasmas\ncauda"}
COLORS = {"lru-folha": "#7a7a7a", "lru-token": "#2a78d6", "rodizio": "#eb6834",
          "fantasma-folha": "#1baf7a", "fantasma-token": "#e87ba4"}
MARKERS = {"lru-folha": "o", "lru-token": "s", "rodizio": "D", "fantasma-folha": "^",
           "fantasma-token": "v"}
STYLES = {"lru-folha": "--"}
WL_NAMES = {"fewshot": "Few-shot", "chat": "Chat com vários turnos"}
INK, MUTED, GRID = "#2b2b2b", "#6b6b6b", "#e4e4e0"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _style(ax):
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelcolor=INK)


def _mean(rows, key):
    return statistics.mean(float(r[key]) for r in rows)


def _by(rows, **kw):
    return [r for r in rows if all(str(r[k]) == str(v) for k, v in kw.items())]


def _wls(rows):
    return [w for w in WL_NAMES if any(r["workload"] == w for r in rows)]


def _log_axis(ax):
    ax.set_xscale("log")
    ax.set_xticks([1, 2, 5, 10, 20, 50, 100])
    ax.set_xticklabels(["1", "2", "5", "10", "20", "50", "100"])


def fig_capacity(rows, out):
    """Em cima: acerto absoluto. Embaixo: ganho sobre o LRU de folha inteira (p.p.)."""
    wls = _wls(rows)
    fracs = sorted({float(r["frac"]) for r in rows})
    fig, axes = plt.subplots(2, len(wls), figsize=(11, 7.5), sharex=True, squeeze=False)
    for j, wl in enumerate(wls):
        sub = _by(rows, workload=wl)
        ax, axg = axes[0][j], axes[1][j]
        ideal = _mean(sub, "ideal_hit_rate") * 100
        ax.axhline(ideal, color=MUTED, linestyle=":", linewidth=1.2)
        ax.text(1.0, ideal + 1.5, "memória infinita", color=MUTED, fontsize=8)
        base = {f: _mean([r for r in sub if r["config"] == "lru-folha" and float(r["frac"]) == f],
                         "hit_rate") * 100 for f in fracs}
        for cid in CONFIG_ORDER:
            ys = [_mean([r for r in sub if r["config"] == cid and float(r["frac"]) == f],
                        "hit_rate") * 100 for f in fracs]
            xs = [f * 100 for f in fracs]
            kw = dict(color=COLORS[cid], marker=MARKERS[cid], markersize=5, linewidth=2,
                      linestyle=STYLES.get(cid, "-"), label=LABELS[cid])
            ax.plot(xs, ys, **kw)
            axg.plot(xs, [y - base[f] for y, f in zip(ys, fracs)], **kw)
        axg.axhline(0, color=MUTED, linewidth=1)
        for a in (ax, axg):
            _log_axis(a)
            _style(a)
        ax.set_title(WL_NAMES[wl], color=INK, fontsize=11)
        ax.set_ylim(0, 100)
        axg.set_xlabel("Capacidade do cache (% do conjunto de trabalho)", color=INK)
    axes[0][0].set_ylabel("Taxa de acerto em tokens (%)", color=INK)
    axes[1][0].set_ylabel("Ganho sobre LRU, folha inteira (p.p.)", color=INK)
    h, l = axes[0][0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.04))
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(out / "fig1_acerto_vs_capacidade.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def fig_budget(sweep, out):
    """Ganho sobre o LRU de folha inteira em função do orçamento de fantasmas."""
    wls = _wls(sweep)
    fig, axes = plt.subplots(1, len(wls), figsize=(11, 4), sharey=True, squeeze=False)
    budgets = sorted({float(r["ghost_budget"]) for r in sweep if r["ghost_budget"] != ""})
    for ax, wl in zip(axes[0], wls):
        sub = _by(sweep, workload=wl)
        base = _mean(_by(sub, config="lru-folha"), "hit_rate") * 100
        tail = _mean(_by(sub, config="lru-token"), "hit_rate") * 100 - base
        ax.axhline(0, color=MUTED, linewidth=1)
        ax.axhline(tail, color=COLORS["lru-token"], linestyle="--", linewidth=1.5,
                   label=LABELS["lru-token"])
        for cid in ("fantasma-folha", "fantasma-token"):
            ys = [_mean([r for r in sub if r["config"] == cid and r["ghost_budget"] != ""
                         and float(r["ghost_budget"]) == b], "hit_rate") * 100 - base
                  for b in budgets]
            ax.plot(range(len(budgets)), ys, color=COLORS[cid], marker=MARKERS[cid], markersize=6,
                    linewidth=2, label=LABELS[cid])
        ax.set_xticks(range(len(budgets)))
        ax.set_xticklabels([f"{b:g}×" for b in budgets])
        frac = float(sub[0]["frac"]) * 100
        ax.set_title(f"{WL_NAMES[wl]} (capacidade = {frac:.0f}%)", color=INK, fontsize=11)
        ax.set_xlabel("Orçamento de fantasmas (múltiplo da capacidade, em tokens de metadado)",
                      color=INK, fontsize=9)
        _style(ax)
    axes[0][0].set_ylabel("Ganho sobre LRU, folha inteira (p.p.)", color=INK)
    h, l = axes[0][0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.06))
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(out / "fig2_orcamento_fantasmas.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def fig_cost(rows, out, frac=0.05):
    """Custo de remoção por pedido e tamanho da árvore, numa capacidade fixa."""
    sub = [r for r in rows if abs(float(r["frac"]) - frac) < 1e-9]
    wls = _wls(sub)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    width = 0.16
    for k, (key, title) in enumerate([("t_evict_us", "Tempo de remoção por pedido (µs)"),
                                      ("nodes", "Nós médios na árvore (vivos + fantasmas)")]):
        ax = axes[k]
        for j, cid in enumerate(CONFIG_ORDER):
            vals = []
            for wl in wls:
                rs = _by(sub, workload=wl, config=cid)
                if key == "nodes":
                    vals.append(_mean(rs, "mean_nodes") + _mean(rs, "mean_ghost_nodes"))
                else:
                    vals.append(_mean(rs, key))
            xs = [i + (j - 2) * (width + 0.01) for i in range(len(wls))]
            ax.bar(xs, vals, width, color=COLORS[cid], label=LABELS[cid])
        ax.set_xticks(range(len(wls)))
        ax.set_xticklabels([WL_NAMES[w] for w in wls])
        ax.set_title(title, color=INK, fontsize=10)
        _style(ax)
        ax.grid(False, axis="x")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.08))
    fig.suptitle(f"Custo (capacidade = {frac*100:.0f}% do conjunto de trabalho)", color=INK, fontsize=11)
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    fig.savefig(out / "fig3_custo.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def summary(rows, sweep, out):
    lines = ["# Resumo dos resultados", "",
             "Média entre as sementes. Acerto = tokens de prompt reaproveitados / tokens de prompt.",
             "Quase acerto = tokens que casaram em nós-fantasma (estavam no cache, saíram e voltaram).", ""]
    fracs = sorted({float(r["frac"]) for r in rows})
    for wl in _wls(rows):
        sub = _by(rows, workload=wl)
        lines += [f"## {WL_NAMES[wl]}", "",
                  f"Conjunto de trabalho médio: {_mean(sub, 'working_set'):,.0f} tokens. "
                  f"Acerto com memória infinita: {_mean(sub, 'ideal_hit_rate'):.1%}.", "",
                  "| Capacidade | " + " | ".join(LABELS[c] for c in CONFIG_ORDER) + " |",
                  "|---:|" + "---:|" * len(CONFIG_ORDER)]
        for f in fracs:
            vals = [_mean([r for r in sub if r["config"] == c and float(r["frac"]) == f], "hit_rate")
                    for c in CONFIG_ORDER]
            lines.append(f"| {f:.0%} | " + " | ".join(f"{v:.1%}" for v in vals) + " |")
        lines += ["", "Quase acertos com fantasmas (folha inteira): " + ", ".join(
            f"{f:.0%}: {_mean([r for r in sub if r['config'] == 'fantasma-folha' and float(r['frac']) == f], 'near_hit_rate'):.1%}"
            for f in fracs), ""]
        sw = _by(sweep, workload=wl)
        base = _mean(_by(sw, config="lru-folha"), "hit_rate")
        lines += [f"Orçamento de fantasmas (capacidade {float(sw[0]['frac']):.0%}), ganho sobre LRU folha inteira:", ""]
        for cid in ("fantasma-folha", "fantasma-token"):
            parts = []
            for b in sorted({float(r["ghost_budget"]) for r in sw if r["ghost_budget"] != ""}):
                v = _mean([r for r in sw if r["config"] == cid and r["ghost_budget"] != ""
                           and float(r["ghost_budget"]) == b], "hit_rate")
                parts.append(f"{b:g}×: {(v - base) * 100:+.2f} p.p.")
            lines.append(f"- {LABELS[cid]}: " + ", ".join(parts))
        lines.append("")
    (out / "resumo.md").write_text("\n".join(lines), encoding="utf-8")


def make_all(out):
    out = Path(out)
    rows = _read(out / "resultados_capacidade.csv")
    sweep = _read(out / "resultados_orcamento.csv")
    fig_capacity(rows, out)
    fig_budget(sweep, out)
    fig_cost(rows, out)
    summary(rows, sweep, out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="resultados")
    make_all(ap.parse_args().out)
