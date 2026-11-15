"""Banco de dados de estado de enlace (LSDB).

Guarda, por origem, a versão válida mais recente do LSA: IP de origem,
sequência, enlaces anunciados e o instante em que essa versão foi aceita.

Também guarda `max_seq`: o maior número de sequência já aceito de cada origem.
Ele NÃO é apagado quando o LSA expira, para que um anúncio antigo que ainda
esteja circulando não seja aceito depois da expiração.
"""

from dataclasses import dataclass

# Resultados de check()
NEW = "novo"
DUPLICATE = "duplicado"
OLD = "antigo"

# Resultados de install()
NEW_ORIGIN = "nova origem"
LINKS_CHANGED = "enlaces alterados"
REFRESHED = "renovação"


@dataclass
class LsaEntry:
    origin: str
    seq: int
    links: dict          # {vizinho: custo}
    received_at: float   # relógio monotônico (para a expiração)
    received_wall: float # hora de parede (para exibir)


class LSDB:
    def __init__(self):
        self.entries = {}   # origem -> LsaEntry
        self.max_seq = {}   # origem -> maior SEQ já aceito (nunca é apagado)

    def check(self, origin, seq):
        """Classifica um LSA recebido como novo, duplicado ou antigo."""
        last = self.max_seq.get(origin, 0)
        if seq > last:
            return NEW
        if seq == last:
            return DUPLICATE
        return OLD

    def install(self, origin, seq, links, now, wall):
        """Registra a versão aceita e diz o que mudou."""
        previous = self.entries.get(origin)
        self.entries[origin] = LsaEntry(origin, seq, dict(links), now, wall)
        self.max_seq[origin] = max(seq, self.max_seq.get(origin, 0))
        if previous is None:
            return NEW_ORIGIN
        if previous.links != links:
            return LINKS_CHANGED
        return REFRESHED

    def expire(self, now, max_age, keep):
        """Remove LSAs com mais de `max_age` segundos (exceto a origem `keep`, o LSA local)."""
        expired = [e for o, e in self.entries.items()
                   if o != keep and now - e.received_at > max_age]
        for entry in expired:
            del self.entries[entry.origin]
        return expired

    def get(self, origin):
        return self.entries.get(origin)

    def topology(self):
        """{origem: {vizinho: custo}} de todos os LSAs válidos (entrada do Dijkstra)."""
        return {o: dict(e.links) for o, e in self.entries.items()}

    def signature(self):
        """Resumo da topologia. Se não mudou, não precisa rodar o Dijkstra de novo
        (é o caso das renovações periódicas, que só trocam a sequência)."""
        nodes = {(origin,) for origin in self.entries}
        edges = {(origin, neighbor, cost)
                 for origin, entry in self.entries.items()
                 for neighbor, cost in entry.links.items()}
        return frozenset(nodes | edges)
