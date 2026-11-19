"""
Testes de validação do RadixCache.   Rodar:  python tests.py

1. Capacidade infinita: o acerto tem que bater EXATAMENTE com uma busca por força
   bruta (maior prefixo comum com qualquer sequência já inserida), em todas as políticas.
2. Capacidade finita, em todas as combinações de política e granularidade:
   invariantes da árvore depois de cada operação (inclusive "nenhum nó vivo abaixo
   de um fantasma"), todo caminho guardado é prefixo de algo inserido, e o acerto
   nunca passa do acerto com capacidade infinita.
3. Nós-fantasma com orçamento zero têm que se comportar EXATAMENTE como o LRU.
4. Casos montados à mão: divisão de nó, escolha LRU, granularidades, proteção do
   caminho atual, criação e revivência de fantasmas, rodízio de cauda.
"""

import random

from radix_cache import RadixCache

CONFIGS = [  # (política, granularidade, tamanho do bloco)
    ("lru", "leaf", 16), ("lru", "block", 4), ("lru", "token", 16),
    ("rr", "token", 16),
    ("ghost", "leaf", 16), ("ghost", "block", 4), ("ghost", "token", 16),
]


def lcp(a, b):
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def random_trace(rng, n=300, alphabet=4, max_len=40):
    """Sequências com alfabeto pequeno e prefixos reaproveitados, para forçar muitas divisões."""
    seqs = []
    for _ in range(n):
        if seqs and rng.random() < 0.7:
            base = rng.choice(seqs)
            s = base[:rng.randint(0, len(base))]
        else:
            s = []
        s = s + [rng.randrange(alphabet) for _ in range(rng.randint(1, max_len))]
        seqs.append(s)
    return seqs


def test_infinite_matches_bruteforce():
    for policy in ("lru", "rr", "ghost"):
        for seed in range(10):
            rng = random.Random(seed)
            cache = RadixCache(capacity=10**12, policy=policy)
            seen = []
            for s in random_trace(rng):
                expected = max((lcp(s, p) for p in seen), default=0)
                assert cache.match_prefix(s) == expected, f"{policy}, seed {seed}: difere da força bruta"
                cache.insert(s)
                seen.append(s)
                cache.check_invariants()


def test_finite_invariants_all_configs():
    for policy, mode, bs in CONFIGS:
        for seed in range(12):
            rng = random.Random(1000 + seed)
            cap = rng.choice([20, 50, 120])
            gcap = rng.choice([0, 10, 50, 200])
            cache = RadixCache(capacity=cap, mode=mode, block_size=bs, policy=policy,
                               rr_chunk=rng.choice([1, 3, 8]), ghost_capacity=gcap)
            ideal = RadixCache(capacity=10**12)
            seen = []
            for s in random_trace(rng, n=200):
                hit, near = cache.match(s)
                assert hit <= ideal.match_prefix(s)
                assert hit + near <= ideal.match_prefix(s)
                if policy != "ghost":
                    assert near == 0
                cache.insert(s)
                ideal.insert(s)
                seen.append(s)
                cache.check_invariants()
            for path in cache.paths():                 # nada inventado: tudo é prefixo de algo inserido
                assert any(seq[:len(path)] == path for seq in seen), f"{policy}/{mode}: caminho inválido"


def test_ghost_with_zero_budget_equals_lru():
    for mode in ("leaf", "token"):
        for seed in range(10):
            rng = random.Random(2000 + seed)
            cap = rng.choice([20, 50, 120])
            lru = RadixCache(capacity=cap, mode=mode, policy="lru")
            ghost = RadixCache(capacity=cap, mode=mode, policy="ghost", ghost_capacity=0)
            for s in random_trace(rng, n=200):
                assert lru.match_prefix(s) == ghost.match_prefix(s), f"{mode}, seed {seed}"
                lru.insert(s)
                ghost.insert(s)
            assert lru.size == ghost.size


def test_split():
    c = RadixCache(capacity=100)
    c.insert([1, 2, 3, 4])
    c.insert([1, 2, 9])
    assert c.num_nodes == 3 and c.splits == 1          # [1,2] -> {[3,4], [9]}
    assert c.match_prefix([1, 2, 3, 5]) == 3
    assert c.match_prefix([1, 2, 9, 9]) == 3
    assert c.match_prefix([7]) == 0
    c.check_invariants()


def _lru_scenario(mode, policy="lru"):
    c = RadixCache(capacity=10, mode=mode, block_size=2, policy=policy)
    c.insert([1, 2, 3, 4])        # A
    c.insert([5, 6, 7])           # B
    c.insert([1, 2, 3, 4])        # A usado de novo -> B passa a ser o menos recente
    c.insert([8, 9, 10, 11])      # C: precisa liberar 1 token (7 + 4 > 10)
    c.check_invariants()
    return c


def test_lru_and_modes():
    leaf = _lru_scenario("leaf")
    assert leaf.match_prefix([5, 6, 7]) == 0           # B saiu inteira
    assert leaf.match_prefix([1, 2, 3, 4]) == 4        # A ficou
    assert leaf.size == 8

    block = _lru_scenario("block")
    assert block.match_prefix([5, 6, 7]) == 1          # saiu um bloco de 2 do fim de B
    assert block.size == 9

    token = _lru_scenario("token")
    assert token.match_prefix([5, 6, 7]) == 2          # saiu só o 1 token necessário
    assert token.size == 10


def test_ghost_created_and_revived():
    c = _lru_scenario("leaf", policy="ghost")
    hit, near = c.match([5, 6, 7])
    assert (hit, near) == (0, 3)                       # B virou fantasma: 3 quase acertos
    assert c.ghost_size == 3 and c.num_ghost_nodes == 1
    c.insert([5, 6, 7])                                # B volta: revive e fica protegida
    c.check_invariants()
    assert c.match_prefix([5, 6, 7]) == 3
    assert c.prot_size == 3 and c.revived_tokens == 3


def test_ghost_tail_and_protection():
    c = _lru_scenario("token", policy="ghost")
    assert c.match([5, 6, 7]) == (2, 1)                # só a cauda [7] virou fantasma
    c.insert([5, 6, 7])                                # revive a cauda (precisa liberar 1 token)
    c.check_invariants()
    assert c.match_prefix([5, 6, 7]) == 3


def test_protected_segment_evicted_last():
    c = RadixCache(capacity=8, mode="leaf", policy="ghost", protected_frac=1.0)
    c.insert([1, 2, 3, 4])        # A
    c.insert([5, 6, 7, 8])        # B
    c.insert([9, 9])              # remove A (mais antiga) -> fantasma
    c.insert([1, 2, 3, 4])        # A revive como protegida (remove B)
    c.insert([6, 6])              # X (não compartilha prefixo com B)
    c.insert([9, 9])              # [9, 9] usado de novo: agora A é a folha mais antiga
    c.check_invariants()
    c.insert([7, 7, 7])           # precisa de 3: o LRU tiraria A; aqui saem as não protegidas
    c.check_invariants()
    assert c.match_prefix([1, 2, 3, 4]) == 4
    assert c.match_prefix([6, 6]) == 0

    lru = RadixCache(capacity=8, mode="leaf", policy="lru")
    for s in ([1, 2, 3, 4], [5, 6, 7, 8], [9, 9], [1, 2, 3, 4], [6, 6], [9, 9], [7, 7, 7]):
        lru.insert(s)
    assert lru.match_prefix([1, 2, 3, 4]) == 0         # no LRU puro, A teria saído


def test_current_path_is_protected():
    c = RadixCache(capacity=6, mode="leaf")
    c.insert([1, 2, 3, 4])
    c.insert([1, 2, 3, 4, 5, 6, 7, 8])                 # estende o próprio caminho: não pode apagá-lo
    assert c.match_prefix([1, 2, 3, 4]) == 4
    assert c.size == 6                                 # só coube o começo da extensão
    c.check_invariants()


def test_round_robin_spreads_eviction():
    c = RadixCache(capacity=12, policy="rr", rr_chunk=1)
    c.insert([1, 1, 1, 1])        # A
    c.insert([2, 2, 2, 2])        # B
    c.insert([3, 3, 3, 3])        # C (cheio: 12)
    c.insert([4, 4])              # precisa de 2: tira 1 token de A e 1 de B
    c.check_invariants()
    assert c.match_prefix([1, 1, 1, 1]) == 3
    assert c.match_prefix([2, 2, 2, 2]) == 3
    assert c.match_prefix([3, 3, 3, 3]) == 4


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} testes passaram.")
