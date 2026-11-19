"""
Geradores de carga (traces de pedidos) com tokens reais.

O texto vem de um corpus real tokenizado com o tiktoken. Por padrão o corpus
são as docstrings da biblioteca padrão do Python (texto real em inglês, que já
vem instalado). Com --corpus PASTA dá para usar qualquer conjunto de .txt.

Cada pedido tem:
  prompt : tokens que o servidor recebe (é sobre ele que se mede o acerto)
  output : tokens da resposta "gerada" (entra no cache junto com o prompt,
           porque o próximo turno do chat contém essa resposta)
"""

import ast
import base64
import os
import random
import sysconfig
import warnings
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Request:
    prompt: list
    output: list


# ------------------------------------------------------------- tokenizador
def get_encoding():
    """Usa o cl100k_base (GPT-4). Se não der para baixar o vocabulário, aceita
    um arquivo .tiktoken local do GPT-2 indicado em TIKTOKEN_GPT2_FILE."""
    import tiktoken
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        path = os.environ.get("TIKTOKEN_GPT2_FILE")
        if not path:
            raise
        ranks = {}
        for line in Path(path).read_bytes().splitlines():
            if line:
                tok, rank = line.split()
                ranks[base64.b64decode(tok)] = int(rank)
        pat = r"""'(?:[sdmt]|ll|ve|re)| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+"""
        return tiktoken.Encoding(name="gpt2_local", pat_str=pat, mergeable_ranks=ranks,
                                 special_tokens={"<|endoftext|>": len(ranks)})


# ------------------------------------------------------------------ corpus
class Corpus:
    def __init__(self, tokens):
        self.tokens = tokens

    @classmethod
    def from_stdlib(cls, enc, max_chars=3_000_000):
        """Junta as docstrings dos arquivos .py da biblioteca padrão (sem importar nada)."""
        stdlib = Path(sysconfig.get_paths()["stdlib"])
        texts, total = [], 0
        for f in sorted(stdlib.rglob("*.py")):
            if "test" in f.parts or "site-packages" in f.parts:
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")   # avisos de sintaxe de arquivos antigos
                    tree = ast.parse(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node)
                    if doc and len(doc) > 80:
                        texts.append(doc)
                        total += len(doc)
            if total >= max_chars:
                break
        return cls(enc.encode("\n\n".join(texts), disallowed_special=()))

    @classmethod
    def from_dir(cls, enc, path):
        text = "\n\n".join(p.read_text(encoding="utf-8", errors="ignore")
                           for p in sorted(Path(path).rglob("*.txt")))
        return cls(enc.encode(text, disallowed_special=()))

    def sample(self, length, rng):
        """Um trecho contínuo de `length` tokens de texto real, em posição aleatória."""
        start = rng.randrange(0, len(self.tokens) - length)
        return self.tokens[start:start + length]


def _zipf_weights(n, s):
    return [1.0 / (i + 1) ** s for i in range(n)]


# ---------------------------------------------------------------- few-shot
def fewshot_trace(corpus, seed, n_requests=3000, n_tasks=30, k_shots=5,
                  sys_len=150, instr_len=(40, 100), shot_len=(150, 300),
                  q_len=(30, 150), out_len=(20, 120), zipf_s=1.1):
    """System prompt comum + uma tarefa (instrução + k exemplos) + pergunta nova.
    A popularidade das tarefas segue Zipf: poucas tarefas recebem a maioria dos pedidos.
    Na árvore: prefixos longos e compartilhados, com folhas curtas (as perguntas)."""
    rng = random.Random(seed)
    system = corpus.sample(sys_len, rng)
    tasks = []
    for _ in range(n_tasks):
        t = system + corpus.sample(rng.randint(*instr_len), rng)
        for _ in range(k_shots):
            t = t + corpus.sample(rng.randint(*shot_len), rng)
        tasks.append(t)
    weights = _zipf_weights(n_tasks, zipf_s)
    order = list(range(n_tasks))
    rng.shuffle(order)                       # a tarefa mais popular não é sempre a 1ª gerada
    trace = []
    for _ in range(n_requests):
        t = order[rng.choices(range(n_tasks), weights)[0]]
        prompt = tasks[t] + corpus.sample(rng.randint(*q_len), rng)
        trace.append(Request(prompt, corpus.sample(rng.randint(*out_len), rng)))
    return trace


# -------------------------------------------------------------------- chat
def chat_trace(corpus, seed, n_requests=3000, concurrency=40, mean_turns=8,
               sys_len=200, user_len=(20, 200), out_len=(100, 500)):
    """Várias conversas intercaladas. Cada turno = system + histórico + nova mensagem,
    e a resposta entra no histórico. Há sempre `concurrency` conversas ativas; a cada
    pedido uma delas (sorteada) fala. Quando uma acaba, outra começa.
    Na árvore: uma cadeia longa por conversa, ou seja, folhas longas."""
    rng = random.Random(seed)
    system = corpus.sample(sys_len, rng)

    def new_session():
        turns = 1 + int(rng.expovariate(1.0 / max(mean_turns - 1, 1e-9)))
        return {"history": list(system), "left": turns}

    active = [new_session() for _ in range(concurrency)]
    trace = []
    for _ in range(n_requests):
        idx = rng.randrange(concurrency)
        s = active[idx]
        prompt = s["history"] + corpus.sample(rng.randint(*user_len), rng)
        out = corpus.sample(rng.randint(*out_len), rng)
        trace.append(Request(prompt, out))
        s["history"] = prompt + out
        s["left"] -= 1
        if s["left"] == 0:
            active[idx] = new_session()
    return trace


WORKLOADS = {"fewshot": fewshot_trace, "chat": chat_trace}
