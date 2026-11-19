# Radix tree com nós-fantasma para cache de prefixos de LLM

Simula o cache de prefixos (KV cache) de um servidor de LLM organizado numa
radix tree, como a RadixAttention do SGLang, e propõe uma variação da
estrutura: a **radix tree com nós-fantasma**. Não roda nenhum modelo: só
conta tokens reais gerados pelo `tiktoken`.

## A variação proposta

- Cada nó é **vivo** (tem KV) ou **fantasma** (guarda só os tokens da aresta e
  as estatísticas, sem KV).
- Remover um nó o transforma em fantasma em vez de apagá-lo.
- **Invariante:** abaixo de um fantasma só há fantasmas (o KV de um filho
  depende do KV do pai). Os nós vivos são fechados por prefixo.
- A busca atravessa fantasmas e conta **quase acertos**: prefixos que estavam
  no cache, saíram e foram pedidos de novo.
- Inserir por um caminho com fantasmas os **revive**, e o conteúdo revivido vai
  para um segmento **protegido**, que só sai depois do não protegido (como no
  SLRU), salvo se passar de 50% da capacidade.
- Os fantasmas têm um orçamento próprio de metadados; os mais antigos são
  podados de vez.

## Configurações comparadas

| id | Política | Referência |
|---|---|---|
| `lru-folha` | LRU, remove a folha inteira | SGLang |
| `lru-token` | LRU, remove só os tokens necessários do fim da folha | — |
| `rodizio` | rodízio entre as folhas, 32 tokens do fim de cada | inspirado no RR-Evict |
| `fantasma-folha` | nós-fantasma, folha inteira | proposta |
| `fantasma-token` | nós-fantasma, cauda por token | proposta |

## Como rodar

```bash
pip install -r requirements.txt
python tests.py                  # validação (deve imprimir "10 testes passaram")
python experiments.py --quick    # teste rápido, ~15 s
python experiments.py            # experimento completo, alguns minutos
```

Os resultados vão para `resultados/`:

- `resultados_capacidade.csv`: experimento 1 (acerto × capacidade, 5 configurações, 2 cargas, 3 sementes)
- `resultados_orcamento.csv`: experimento 2 (orçamento de fantasmas de 0× a 4× a capacidade)
- `fig1_acerto_vs_capacidade.png`, `fig2_orcamento_fantasmas.png`, `fig3_custo.png`
- `resumo.md`: tabelas com as médias

Para usar outros textos como corpus: `python experiments.py --corpus pasta_com_txts`.

## Arquivos

| Arquivo | O que tem |
|---|---|
| `radix_cache.py` | A árvore: busca, inserção com divisão de nó, políticas LRU, rodízio e nós-fantasma |
| `workloads.py` | Tokenizador, corpus e geradores das cargas few-shot e chat |
| `experiments.py` | Laço de simulação, métricas e os dois experimentos |
| `plots.py` | Gráficos e tabela-resumo a partir dos CSVs |
| `tests.py` | Testes de validação |

## Decisões de modelagem

1. **Acerto em tokens**: tokens do prompt com KV no cache ÷ tokens totais de prompt.
2. **O que entra no cache**: prompt + resposta, porque o próximo turno do chat contém a resposta.
3. **Pedidos em sequência**, um por vez. O caminho do pedido atual fica travado e não pode ser removido nem podado.
4. **Se o pedido não cabe**, guarda-se só o começo; fantasmas do caminho são revividos de cima para baixo enquanto couberem.
5. **Orçamento de fantasmas** padrão = 1× a capacidade, em tokens de metadado. Um token de metadado custa ~4 bytes; um token de KV custa centenas de KB num modelo de 7B, então o custo de memória dos fantasmas é desprezível.
6. **Segmento protegido**: até 50% da capacidade.
7. **Rodízio de cauda**: é uma versão simplificada do RR-Evict, que percorre as folhas em ordem de último acesso, de onde parou, tirando 32 tokens de cada.
8. **Nós não são juntados de volta** depois de remoções, como no SGLang.
9. **Capacidade relativa**: fração do "conjunto de trabalho", o total de tokens que a árvore guardaria com memória infinita.
10. **Corpus padrão**: docstrings da biblioteca padrão do Python (texto real em inglês).

## Onde está cada parte da proposta no código

- `RadixCache._drop` e `_evict_tail`: como um nó vivo vira fantasma (inteiro ou só a cauda).
- `RadixCache.insert` e `_revive`: como os fantasmas do caminho voltam a ser vivos.
- `RadixCache._pop_victim`: a ordem de remoção entre o segmento não protegido e o protegido.
- `tests.py`: o teste com memória infinita compara com força bruta, e o teste de
  orçamento zero confere que os fantasmas sem orçamento se comportam igual ao LRU.

## Resultados do artigo

Os números e gráficos do artigo vêm da pasta `resultado cl100k/`: execução
completa com o tokenizador `cl100k_base`, 3 sementes e 3.000 pedidos por carga.