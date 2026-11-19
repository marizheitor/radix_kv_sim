"""
Radix tree para cache de prefixos de KV (no estilo da RadixAttention do SGLang),
com uma variação proposta pelo grupo: a RADIX TREE COM NÓS-FANTASMA.

Ideia geral
-----------
Cada nó guarda uma sequência de tokens (aresta comprimida). Um caminho da raiz
até um nó representa um prefixo de prompt. O tamanho do cache é o total de
tokens com KV guardado, porque cada token corresponde a uma entrada de KV.

Políticas de remoção (parâmetro `policy`)
-----------------------------------------
  - "lru"   : remove a folha viva acessada há mais tempo                  (SGLang)
  - "rr"    : rodízio de cauda: visita as folhas em rodízio e tira um
              pedaço de `rr_chunk` tokens do fim de cada uma      (inspirado no RR-Evict)
  - "ghost" : radix tree com nós-fantasma (proposta do grupo), descrita abaixo

Granularidade (parâmetro `mode`, vale para "lru" e "ghost")
-----------------------------------------------------------
  - "leaf"  : remove a folha inteira
  - "block" : remove `block_size` tokens do fim da folha por vez
  - "token" : remove só os tokens necessários do fim da folha

Nós-fantasma (policy="ghost")
-----------------------------
  - Estados de nó: VIVO (tem KV) ou FANTASMA (guarda só os tokens da aresta e as
    estatísticas, sem KV; custa só metadados).
  - Remover um nó vivo o transforma em fantasma, em vez de apagá-lo da árvore.
  - Invariante: se um nó é fantasma, todos os descendentes também são, porque
    o KV de um filho depende do KV do pai. Os nós vivos formam um conjunto
    fechado por prefixo a partir da raiz.
  - A busca atravessa fantasmas: os tokens casados em fantasmas são "quase
    acertos" (um prefixo que estava no cache, foi removido e voltou).
  - Inserir por um caminho com fantasmas os REVIVE. Um nó revivido provou que é
    reaproveitado e vai para o segmento PROTEGIDO.
  - Remoção em dois segmentos (como no SLRU): primeiro saem folhas não
    protegidas; as protegidas só saem quando não há outras, ou quando o
    segmento protegido passa de `protected_frac` da capacidade.
  - Os fantasmas têm orçamento próprio (`ghost_capacity`, em tokens de
    metadado); quando passa dele, os fantasmas-folha mais antigos são podados
    de vez da árvore.
"""

import heapq
import itertools
import time
from collections import deque


class Node:
    __slots__ = ("key", "children", "parent", "last_access", "hits", "alive", "lock",
                 "ghost", "protected", "live_children")

    def __init__(self, key, parent):
        self.key = key            # list[int]: tokens desta aresta
        self.children = {}        # primeiro token do filho -> Node (vivos e fantasmas)
        self.parent = parent
        self.last_access = 0      # "relógio" do último acesso
        self.hits = 0             # nº de acessos
        self.alive = True         # False depois de sair da árvore
        self.lock = 0             # > 0 enquanto está no caminho do pedido atual
        self.ghost = False        # True = fantasma (sem KV)
        self.protected = False    # True = no segmento protegido (só na política "ghost")
        self.live_children = 0    # nº de filhos vivos


def _common_len(key, tokens, start):
    """Quantos tokens de `key` casam com tokens[start:]."""
    L = len(key)
    if tokens[start:start + L] == key:      # caminho rápido: compara a aresta inteira (em C)
        return L
    m = min(L, len(tokens) - start)
    j = 0
    while j < m and key[j] == tokens[start + j]:
        j += 1
    return j


class RadixCache:
    MODES = ("leaf", "block", "token")
    POLICIES = ("lru", "rr", "ghost")

    def __init__(self, capacity, mode="leaf", block_size=16, policy="lru",
                 rr_chunk=32, ghost_capacity=None, protected_frac=0.5):
        if mode not in self.MODES:
            raise ValueError(f"modo inválido: {mode}")
        if policy not in self.POLICIES:
            raise ValueError(f"política inválida: {policy}")
        self.capacity = capacity
        self.mode = mode
        self.block_size = block_size
        self.policy = policy
        self.rr_chunk = rr_chunk
        self.ghost_capacity = (capacity if ghost_capacity is None else ghost_capacity) \
            if policy == "ghost" else 0
        self.prot_cap = protected_frac * capacity

        self.root = Node([], None)
        self.size = 0              # tokens com KV (nós vivos)
        self.ghost_size = 0        # tokens guardados só como metadado (fantasmas)
        self.prot_size = 0         # tokens vivos no segmento protegido
        self.num_nodes = 0         # nós vivos, sem contar a raiz
        self.num_ghost_nodes = 0
        self.clock = 0

        # Heaps com remoção preguiçosa: (last_access, seq, nó); entradas velhas são
        # descartadas ao sair do heap.
        self._heap = []            # folhas vivas não protegidas
        self._pheap = []           # folhas vivas protegidas
        self._gheap = []           # folhas-fantasma (para a poda)
        self._seq = itertools.count()
        self._rr_cursor = -1       # rodízio: last_access da última folha visitada

        # Contadores para as métricas
        self.evicted_tokens = 0
        self.evict_ops = 0
        self.splits = 0
        self.revived_tokens = 0
        self.pruned_ghost_tokens = 0
        self.t_evict = 0.0         # tempo total gasto em remoções e podas (s)

    # ------------------------------------------------------------------ busca
    def match(self, tokens):
        """Retorna (acerto, quase_acerto): tokens iniciais casados em nós vivos, e
        tokens casados logo depois em fantasmas. Somente leitura."""
        node, i, n = self.root, 0, len(tokens)
        live = None
        while i < n:
            child = node.children.get(tokens[i])
            if child is None:
                break
            if child.ghost and live is None:
                live = i                     # a partir daqui não há mais KV
            k = _common_len(child.key, tokens, i)
            i += k
            if k < len(child.key):
                break
            node = child
        if live is None:
            live = i
        return live, i - live

    def match_prefix(self, tokens):
        return self.match(tokens)[0]

    # --------------------------------------------------------------- inserção
    def insert(self, tokens):
        """Insere `tokens` (prompt + resposta), revive fantasmas do caminho, marca o
        caminho como usado agora e remove o que for preciso. Retorna os tokens que
        ganharam KV."""
        self.clock += 1
        node, i, n = self.root, 0, len(tokens)
        path = []
        while i < n:
            child = node.children.get(tokens[i])
            if child is None:
                break
            k = _common_len(child.key, tokens, i)
            if k < len(child.key):           # divergiu no meio da aresta: divide o nó
                child = self._split(child, k)
            i += k
            node = child
            path.append(node)

        for nd in path:                      # atualiza o LRU de todo o caminho
            nd.last_access = self.clock
            nd.hits += 1

        ghosts = [nd for nd in path if nd.ghost]      # sempre o final do caminho
        remaining = n - i
        need = self.size + sum(len(g.key) for g in ghosts) + remaining - self.capacity

        for nd in path:                      # o caminho atual não pode ser removido nem podado
            nd.lock += 1
        if need > 0:
            self.evict(need)
        free = self.capacity - self.size
        added = 0
        for g in ghosts:                     # revive de cima para baixo enquanto couber
            if len(g.key) > free:
                break
            self._revive(g)
            free -= len(g.key)
            added += len(g.key)
        for nd in path:
            nd.lock -= 1

        for nd in path:                      # prioridades mudaram: atualiza os heaps
            self._push(nd)

        last = path[-1] if path else self.root
        if remaining > 0 and not last.ghost and free > 0:
            take = min(remaining, free)      # se não coube, guarda só o começo
            new = Node(tokens[i:i + take], last)
            new.last_access = self.clock
            new.hits = 1
            last.children[new.key[0]] = new
            last.live_children += 1
            self.size += take
            self.num_nodes += 1
            self._push(new)
            added += take
        self._prune_ghosts()
        return added

    def _split(self, child, k):
        """Divide `child` em [key[:k]] -> [key[k:]] e devolve o nó de cima.
        O nó de cima herda o estado (vivo/fantasma, protegido) do original."""
        parent = child.parent
        mid = Node(child.key[:k], parent)
        mid.last_access = child.last_access
        mid.hits = child.hits
        mid.ghost = child.ghost
        mid.protected = child.protected
        mid.live_children = 0 if child.ghost else 1
        child.key = child.key[k:]
        child.parent = mid
        mid.children[child.key[0]] = child
        parent.children[mid.key[0]] = mid
        if mid.ghost:
            self.num_ghost_nodes += 1
        else:
            self.num_nodes += 1
        self.splits += 1
        return mid

    def _revive(self, nd):
        L = len(nd.key)
        nd.ghost = False
        nd.protected = True                  # provou que é reaproveitado
        self.ghost_size -= L
        self.size += L
        self.prot_size += L
        self.num_ghost_nodes -= 1
        self.num_nodes += 1
        nd.parent.live_children += 1
        self.revived_tokens += L

    # ---------------------------------------------------------------- remoção
    def evict(self, need):
        """Libera pelo menos `need` tokens de KV (ou tudo o que for possível)."""
        t0 = time.perf_counter()
        if self.policy == "rr":
            freed = self._evict_rr(need)
        else:
            freed = self._evict_lru(need)
        self._maybe_compact()
        self.t_evict += time.perf_counter() - t0
        return freed

    def _evict_lru(self, need):
        freed = 0
        held = []                            # folhas travadas: voltam ao heap no fim
        while freed < need:
            nd = self._pop_victim()
            if nd is None:
                break
            if nd.lock:
                held.append(nd)
                continue
            take = len(nd.key)
            if self.mode == "block":
                take = min(take, self.block_size)
            elif self.mode == "token":
                take = min(take, need - freed)
            self._evict_tail(nd, take)
            freed += take
        for nd in held:
            self._push(nd)
        return freed

    def _evict_rr(self, need):
        """Rodízio: percorre as folhas vivas em ordem de último acesso, a partir de
        onde parou na chamada anterior, tirando `rr_chunk` tokens de cada uma."""
        leaves = sorted((nd for nd in self.nodes() if self._is_live_leaf(nd) and not nd.lock),
                        key=lambda nd: nd.last_access)
        after = [nd for nd in leaves if nd.last_access > self._rr_cursor]
        before = [nd for nd in leaves if nd.last_access <= self._rr_cursor]
        queue = deque(after + before)
        freed = 0
        while freed < need and queue:
            nd = queue.popleft()
            if not self._is_live_leaf(nd):
                continue
            take = min(self.rr_chunk, len(nd.key), need - freed)
            parent = nd.parent
            self._evict_tail(nd, take)
            freed += take
            self._rr_cursor = nd.last_access
            if nd.alive and self._is_live_leaf(nd):
                queue.append(nd)             # ainda tem cauda: volta para o fim da fila
            elif parent is not self.root and self._is_live_leaf(parent) and not parent.lock:
                queue.append(parent)         # o pai virou folha
        return freed

    def _evict_tail(self, nd, take):
        """Tira `take` tokens do fim da folha viva `nd` (ou a folha inteira)."""
        self.evicted_tokens += take
        self.evict_ops += 1
        if take == len(nd.key):
            self._drop(nd)
            return
        if self.policy == "ghost":
            # o fim cortado vira um filho fantasma; o começo continua vivo
            upper = self._split(nd, len(nd.key) - take)
            self._drop(nd)                   # nd agora é só a cauda
            self._push(upper)
        else:
            if nd.protected:
                self.prot_size -= take
            del nd.key[-take:]
            self.size -= take
            self._push(nd)

    def _drop(self, nd):
        """Tira o KV de uma folha viva inteira: vira fantasma (política "ghost") ou sai da árvore."""
        L = len(nd.key)
        parent = nd.parent
        self.size -= L
        if nd.protected:
            self.prot_size -= L
            nd.protected = False
        parent.live_children -= 1
        self.num_nodes -= 1
        if self.policy == "ghost":
            nd.ghost = True
            self.ghost_size += L
            self.num_ghost_nodes += 1
            if not nd.children:
                self._push(nd)
        else:
            del parent.children[nd.key[0]]
            nd.alive = False
        if parent is not self.root:
            self._push(parent)               # o pai pode ter virado folha viva

    def _prune_ghosts(self):
        """Poda definitiva dos fantasmas-folha mais antigos quando o orçamento estoura."""
        if self.ghost_size <= self.ghost_capacity:
            return
        t0 = time.perf_counter()
        held = []
        while self.ghost_size > self.ghost_capacity and self._gheap:
            stamp, _, nd = heapq.heappop(self._gheap)
            if not (nd.alive and nd.ghost and not nd.children and stamp == nd.last_access):
                continue
            if nd.lock:
                held.append(nd)
                continue
            parent = nd.parent
            del parent.children[nd.key[0]]
            nd.alive = False
            self.ghost_size -= len(nd.key)
            self.num_ghost_nodes -= 1
            self.pruned_ghost_tokens += len(nd.key)
            if parent.ghost and not parent.children:
                self._push(parent)
        for nd in held:
            self._push(nd)
        self.t_evict += time.perf_counter() - t0

    # ---------------------------------------------------------- heaps e testes
    def _is_live_leaf(self, nd):
        return nd.alive and not nd.ghost and nd.live_children == 0 and nd is not self.root

    def _pop_valid(self, heap, protected):
        while heap:
            stamp, _, nd = heapq.heappop(heap)
            if self._is_live_leaf(nd) and nd.protected == protected and stamp == nd.last_access:
                return nd
        return None

    def _pop_victim(self):
        """Folha a remover: primeiro as não protegidas, salvo se o segmento protegido
        passou da sua cota."""
        order = [(self._heap, False), (self._pheap, True)]
        if self.prot_size > self.prot_cap:
            order.reverse()
        for heap, prot in order:
            nd = self._pop_valid(heap, prot)
            if nd is not None:
                return nd
        return None

    def _push(self, nd):
        """Põe o nó no heap certo, se ele for candidato (folha viva ou folha-fantasma)."""
        if nd is self.root or not nd.alive:
            return
        entry = (nd.last_access, next(self._seq), nd)
        if nd.ghost:
            if not nd.children:
                heapq.heappush(self._gheap, entry)
        elif nd.live_children == 0:
            heapq.heappush(self._pheap if nd.protected else self._heap, entry)

    def _maybe_compact(self):
        """Reconstrói os heaps quando há entradas velhas demais."""
        total = len(self._heap) + len(self._pheap) + len(self._gheap)
        if total > 4 * (self.num_nodes + self.num_ghost_nodes) + 1024:
            self._heap, self._pheap, self._gheap = [], [], []
            for nd in self.nodes():
                self._push(nd)

    def nodes(self):
        """Todos os nós da árvore (vivos e fantasmas), sem a raiz."""
        stack = list(self.root.children.values())
        while stack:
            nd = stack.pop()
            yield nd
            stack.extend(nd.children.values())

    def leaves(self):
        return [nd for nd in self.nodes() if self._is_live_leaf(nd)]

    def check_invariants(self):
        """Confere a consistência da árvore (usado nos testes)."""
        size = gsize = psize = live = ghosts = 0
        for nd in self.nodes():
            assert nd.alive, "nó removido ainda está na árvore"
            assert len(nd.key) > 0, "aresta vazia"
            assert nd.parent.children.get(nd.key[0]) is nd, "filho indexado pelo token errado"
            assert nd.lock == 0, "trava esquecida"
            if nd.parent.ghost:
                assert nd.ghost, "nó vivo abaixo de um fantasma"
            assert nd.live_children == sum(not c.ghost for c in nd.children.values()), \
                "contagem de filhos vivos errada"
            if nd.ghost:
                assert not nd.protected, "fantasma marcado como protegido"
                gsize += len(nd.key)
                ghosts += 1
            else:
                size += len(nd.key)
                live += 1
                if nd.protected:
                    psize += len(nd.key)
        assert self.root.live_children == sum(not c.ghost for c in self.root.children.values())
        assert size == self.size, f"tamanho inconsistente: {size} != {self.size}"
        assert gsize == self.ghost_size, "tamanho dos fantasmas inconsistente"
        assert psize == self.prot_size, "tamanho protegido inconsistente"
        assert live == self.num_nodes and ghosts == self.num_ghost_nodes, "nº de nós inconsistente"
        assert self.size <= self.capacity, "passou da capacidade"
        assert self.ghost_size <= self.ghost_capacity, "passou do orçamento de fantasmas"

    def paths(self, include_ghosts=True):
        """Todas as sequências raiz->nó (usado nos testes)."""
        out = []
        stack = [(c, list(c.key)) for c in self.root.children.values()]
        while stack:
            nd, seq = stack.pop()
            if include_ghosts or not nd.ghost:
                out.append(seq)
            for c in nd.children.values():
                stack.append((c, seq + c.key))
        return out
