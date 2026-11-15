import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dijkstra import Route, build_graph, compute_routes, diff_routes  # noqa: E402

R1, R2, R3, R4, R5 = (f"10.0.0.{i}" for i in range(1, 6))

# Topologia do PLANO.md (custos por direção)
TOPOLOGY = {
    R1: {R2: 10, R3: 5},
    R2: {R1: 10, R4: 2},
    R3: {R1: 7, R4: 7, R5: 13},
    R4: {R2: 2, R3: 7, R5: 4},
    R5: {R3: 13, R4: 4},
}


def routes(topology, source=R1, active=None, tie="aleatorio", seed=0, previous=None):
    active = set(topology[source]) if active is None else active
    return compute_routes(topology, source, active, tie, random.Random(seed), previous)


class TestDijkstra(unittest.TestCase):
    def test_plan_topology_from_r1(self):
        r = routes(TOPOLOGY)
        self.assertNotIn(R1, r)                         # sem rota para si
        self.assertEqual(r[R2], Route(10, R2, 1))
        self.assertEqual(r[R3], Route(5, R3, 1))
        self.assertEqual(r[R4].cost, 12)                # empate R2/R3
        self.assertEqual(r[R4].options, 2)
        self.assertEqual(r[R5].cost, 16)                # R2-R4-R5 e R3-R4-R5
        self.assertEqual(r[R5].options, 2)

    def test_asymmetric_cost(self):
        self.assertEqual(routes(TOPOLOGY, source=R3)[R1], Route(7, R1, 1))
        self.assertEqual(routes(TOPOLOGY, source=R1)[R3], Route(5, R3, 1))

    def test_tie_break_lowest_ip(self):
        r = routes(TOPOLOGY, tie="menor_ip")
        self.assertEqual(r[R4].next_hop, R2)
        self.assertEqual(r[R5].next_hop, R2)

    def test_tie_break_random_uses_both(self):
        hops = {routes(TOPOLOGY, seed=s)[R4].next_hop for s in range(30)}
        self.assertEqual(hops, {R2, R3})

    def test_keeps_previous_choice_when_still_optimal(self):
        previous = {R4: Route(12, R3, 2)}
        for seed in range(10):
            self.assertEqual(routes(TOPOLOGY, seed=seed, previous=previous)[R4].next_hop, R3)

    def test_edge_needs_both_ends(self):
        topo = {k: dict(v) for k, v in TOPOLOGY.items()}
        del topo[R4][R5]                     # R4 não reconhece mais o enlace com R5
        self.assertNotIn(R5, build_graph(topo)[R4])
        self.assertNotIn(R4, build_graph(topo)[R5])
        self.assertEqual(routes(topo)[R5], Route(18, R3, 1))   # só via R3-R5

    def test_node_without_lsa_is_unreachable(self):
        topo = {k: v for k, v in TOPOLOGY.items() if k != R5}  # R5 sem LSA
        self.assertNotIn(R5, routes(topo))

    def test_next_hop_must_be_active(self):
        r = routes(TOPOLOGY, active={R3})
        self.assertEqual(r[R4], Route(12, R3, 1))
        self.assertEqual(r[R2], Route(14, R3, 1))   # R3-R4-R2

    def test_isolated(self):
        self.assertEqual(routes({R1: {}}, active=set()), {})

    def test_diff(self):
        old = {R2: Route(10, R2), R3: Route(5, R3)}
        new = {R2: Route(1, R2), R4: Route(3, R2)}
        kinds = {(k, d) for k, d, *_ in diff_routes(old, new)}
        self.assertEqual(kinds, {("ALTERADA", R2), ("REMOVIDA", R3), ("NOVA", R4)})


if __name__ == "__main__":
    unittest.main()
