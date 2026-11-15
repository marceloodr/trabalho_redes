"""Cálculo das rotas: grafo a partir da LSDB + Dijkstra implementado pelo grupo.

`heapq` é só uma fila de prioridade (estrutura de dados); o algoritmo de
caminhos mínimos está todo aqui.
"""

import heapq
from dataclasses import dataclass

from protocol import ip_key


@dataclass(frozen=True)
class Route:
    cost: int
    next_hop: str
    options: int = 1   # quantos próximos saltos empatam no menor custo


def build_graph(topology):
    """Grafo dirigido {u: {v: custo}}.

    A aresta u->v (com o custo anunciado por u) só existe se o LSA de v também
    anuncia u, ou seja, as duas extremidades reconhecem o enlace.
    """
    graph = {u: {} for u in topology}
    for u, links in topology.items():
        for v, cost in links.items():
            if v in topology and u in topology[v]:
                graph[u][v] = cost
    return graph


def shortest_paths(graph, source):
    """Dijkstra a partir de `source`.

    Retorna (dist, first_hops):
      dist[v]       – custo mínimo até v
      first_hops[v] – conjunto de vizinhos de `source` pelos quais se chega a v
                      com esse custo mínimo (mais de um = caminhos empatados)
    """
    dist = {source: 0}
    first_hops = {source: set()}
    done = set()
    heap = [(0, source)]

    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue          # entrada velha na fila (já achamos caminho melhor)
        done.add(u)

        for v, cost in graph.get(u, {}).items():
            new_dist = d + cost
            # saindo da origem, o primeiro salto é o próprio v; senão herda o de u
            hops = {v} if u == source else first_hops[u]
            if v not in dist or new_dist < dist[v]:
                dist[v] = new_dist
                first_hops[v] = set(hops)
                heapq.heappush(heap, (new_dist, v))
            elif new_dist == dist[v] and v not in done:
                first_hops[v] |= hops      # outro caminho com o mesmo custo
    # Como os custos são > 0, quando v sai da fila todos os seus predecessores
    # de custo mínimo já saíram antes, então first_hops[v] está completo.
    return dist, first_hops


def compute_routes(topology, source, active_neighbors, tie_break, rng, previous=None):
    """Tabela de roteamento {destino: Route}.

    - não inclui rota para si próprio;
    - o próximo salto é sempre um vizinho ativo;
    - empate: "aleatorio" sorteia (mas mantém a escolha anterior se ela continua
      ótima, para a rota não "mudar" à toa) ou "menor_ip".
    """
    previous = previous or {}
    graph = build_graph(topology)
    # Só saímos da origem por vizinhos ativos (o LSA local já só lista ativos,
    # isto apenas garante a regra mesmo se o LSA local estiver defasado).
    graph[source] = {v: c for v, c in graph.get(source, {}).items() if v in active_neighbors}
    dist, first_hops = shortest_paths(graph, source)

    routes = {}
    for dest, cost in dist.items():
        if dest == source:
            continue
        candidates = sorted((h for h in first_hops[dest] if h in active_neighbors), key=ip_key)
        if not candidates:
            continue
        old = previous.get(dest)
        if tie_break == "menor_ip":
            hop = candidates[0]
        elif old and old.cost == cost and old.next_hop in candidates:
            hop = old.next_hop
        else:
            hop = rng.choice(candidates)
        routes[dest] = Route(cost, hop, len(candidates))
    return routes


ADDED, REMOVED, CHANGED = "NOVA", "REMOVIDA", "ALTERADA"


def diff_routes(old, new):
    """Lista de (tipo, destino, rota_antiga, rota_nova) com o que mudou."""
    changes = []
    for dest in sorted(set(old) | set(new), key=ip_key):
        a, b = old.get(dest), new.get(dest)
        if a is None:
            changes.append((ADDED, dest, None, b))
        elif b is None:
            changes.append((REMOVED, dest, a, None))
        elif (a.cost, a.next_hop) != (b.cost, b.next_hop):
            changes.append((CHANGED, dest, a, b))
    return changes
