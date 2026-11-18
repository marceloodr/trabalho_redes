"""Cenários A–H do relatório executados numa rede simulada (relógio falso)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from simnet import SimNet  # noqa: E402
from router import CommandError  # noqa: E402
import seqstore  # noqa: E402

R1, R2, R3, R4, R5, R6 = (f"10.0.0.{i}" for i in range(1, 7))

# Topologia de teste: custo de cada roteador até cada vizinho
CONFIG = {
    R1: {R2: 10, R3: 5},
    R2: {R1: 10, R4: 2},
    R3: {R1: 7, R4: 7, R5: 13},
    R4: {R2: 2, R3: 7, R5: 4},
    R5: {R3: 13, R4: 4},
}


def table(router):
    return {d: (r.cost, r.next_hop) for d, r in router.routes.items()}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.net = SimNet(self.tmp.name)
        for ip, nbrs in CONFIG.items():
            self.net.add(ip, nbrs)
        self.net.advance(2)

    def tearDown(self):
        self.tmp.cleanup()

    def r(self, ip):
        return self.net.routers[ip]

    def read_config(self, ip):
        with open(os.path.join(self.tmp.name, ip, "roteadores.txt")) as f:
            return f.read()

    def messages(self, ip):
        """Mensagens DATA exibidas ao usuário (ignora as tabelas impressas)."""
        return [t for t in self.net.received[ip] if ">>> Mensagem" in t]


class TestScenarios(Base):
    def test_A_initial_convergence(self):
        self.assertEqual(table(self.r(R1)), {
            R2: (10, R2), R3: (5, R3), R4: (12, R2), R5: (16, R2)})   # empate -> menor IP
        self.assertEqual(table(self.r(R3)), {
            R1: (7, R1), R2: (9, R4), R4: (7, R4), R5: (11, R4)})
        for ip in CONFIG:
            self.assertEqual(set(self.r(ip).lsdb.entries), set(CONFIG))
            self.assertTrue(all(n.active for n in self.r(ip).neighbors.values()))

    def test_periodic_refresh_does_not_rerun_dijkstra(self):
        self.net.clear_logs()
        seq_before = self.r(R1).lsdb.get(R5).seq
        self.net.advance(25)
        self.assertGreater(self.r(R1).lsdb.get(R5).seq, seq_before)   # renovou
        self.assertTrue(self.net.logs(R1, "LSA_ACEITO"))
        self.assertEqual(self.net.logs(R1, "DIJKSTRA_EXECUTADO"), [])  # sem mudança

    def test_flooding_not_back_to_sender(self):
        self.net.clear_logs()
        self.net.advance(10)
        for src, dst, text in self.net.sent:
            if text.startswith(f"#{R5};") and src == R4:
                self.assertNotEqual(dst, R5)

    def test_B_new_router(self):
        self.net.add(R6, {R4: 6, R5: 3})
        self.net.advance(6)
        self.assertNotIn(R6, self.r(R1).routes)          # ninguém configurou R6 ainda
        self.assertFalse(self.r(R6).neighbors[R4].active)

        self.r(R4).cmd_add(R6, 6)
        self.r(R5).cmd_add(R6, 3)
        self.net.deliver()
        # sincronização imediata: R6 conhece toda a LSDB sem esperar 10 s
        self.assertEqual(set(self.r(R6).lsdb.entries), set(CONFIG) | {R6})
        self.assertEqual(self.r(R1).routes[R6].cost, 12 + 6)
        self.assertIn(f"{R6};6", self.read_config(R4))

    def test_C_link_failure(self):
        self.r(R2).cmd_down(R4)
        self.net.deliver()
        self.assertFalse(self.r(R2).neighbors[R4].active)
        self.assertTrue(self.r(R4).neighbors[R2].active)      # R4 ainda não percebeu
        self.assertEqual(table(self.r(R1))[R4], (12, R3))      # mas aresta já sai do grafo

        self.net.advance(16)
        self.assertFalse(self.r(R4).neighbors[R2].active)
        self.assertTrue(self.net.logs(R4, "VIZINHO_INATIVO"))
        # R2 descarta HELLO e LSA vindos de R4 com o enlace desativado
        self.assertTrue(any("enlace desativado" in l for l in self.net.logs(R2, "HELLO_DESCARTADO")))

    def test_C_link_recovery_needs_hello(self):
        self.r(R2).cmd_down(R4)
        self.net.advance(16)
        self.r(R2).cmd_up(R4)
        self.net.deliver()
        self.assertTrue(self.r(R2).neighbors[R4].active)
        self.assertEqual(table(self.r(R1))[R4], (12, R2))

    def test_D_router_failure_and_E_recovery(self):
        seq_before = self.r(R4).my_seq
        self.net.crash(R4)
        self.net.advance(16)
        for ip in (R2, R3, R5):
            self.assertFalse(self.r(ip).neighbors[R4].active)
        self.assertNotIn(R4, self.r(R1).routes)               # inalcançável antes de expirar
        self.assertIn(R4, self.r(R1).lsdb.entries)
        self.assertEqual(table(self.r(R1))[R5], (18, R3))

        self.net.advance(20)                                  # > 30 s desde o último LSA de R4
        self.assertNotIn(R4, self.r(R1).lsdb.entries)
        self.assertTrue(self.net.logs(R1, "LSA_EXPIRADO"))
        self.assertIn(R4, self.r(R1).lsdb.max_seq)            # maior SEQ mantido

        # E: reinicia R4 na mesma pasta -> continua a sequência do seq.txt
        self.net.restart(R4)
        first_lsa = self.net.logs(R4, "LSA_GERADO")[0]
        self.assertIn(f"SEQ={seq_before + 1}", first_lsa)
        self.net.advance(2)
        self.assertEqual(table(self.r(R1))[R4], (12, R2))
        self.assertEqual(table(self.r(R1))[R5], (16, R2))

    def test_E_restart_without_seq_file_is_ignored(self):
        self.net.crash(R4)
        os.remove(os.path.join(self.tmp.name, R4, "seq.txt"))
        self.net.advance(1)
        self.net.restart(R4)
        self.net.advance(2)
        self.assertTrue(any("antigo" in l for l in self.net.logs(R2, "LSA_DESCARTADO")))

    def test_F_duplicate_and_old(self):
        stored = self.r(R2).lsdb.get(R5)
        self.net.clear_logs()
        self.net.advance(0.5)
        self.net.clear_logs()
        age_before = self.r(R2).lsdb.get(R5).received_at

        self.r(R1).cmd_replay(R2, R5, "dup")
        self.net.deliver()
        self.r(R1).cmd_replay(R2, R5, "old")
        self.net.deliver()

        dropped = self.net.logs(R2, "LSA_DESCARTADO")
        self.assertTrue(any("duplicado" in l for l in dropped))
        self.assertTrue(any("antigo" in l for l in dropped))
        self.assertEqual(self.r(R2).lsdb.get(R5).received_at, age_before)   # validade não renovada
        self.assertFalse([s for s in self.net.sent if s[0] == R2 and s[2].startswith(f"#{R5};")])
        self.assertEqual(stored.seq, self.r(R2).lsdb.get(R5).seq)

    def test_F_old_after_expiry_still_rejected(self):
        self.net.crash(R5)
        self.net.advance(32)
        self.assertNotIn(R5, self.r(R4).lsdb.entries)
        old_seq = self.r(R4).lsdb.max_seq[R5]
        self.net.inject(R2, R4, f"#{R5};{old_seq}*{R4};4")
        self.assertTrue(any("duplicado" in l for l in self.net.logs(R4, "LSA_DESCARTADO")))

    def test_own_lsa_discarded(self):
        self.net.inject(R2, R1, f"#{R1};999999*{R2};1")
        self.assertTrue(any("próprio" in l for l in self.net.logs(R1, "LSA_DESCARTADO")))
        self.assertLess(self.r(R1).my_seq, 999999)

    def test_lsa_from_non_neighbor_discarded(self):
        self.net.inject(R5, R1, f"#{R5};999*{R4};1")
        self.assertTrue(self.net.logs(R1, "LSA_DESCARTADO"))
        self.assertLess(self.r(R1).lsdb.get(R5).seq, 999)

    def test_malformed_logged(self):
        self.net.inject(R2, R1, "#10.0.0.2;abc")
        self.assertTrue(self.net.logs(R1, "MSG_DESCARTADA"))

    def test_G_cost_change(self):
        self.r(R1).cmd_cost(R2, 1)
        self.net.deliver()
        self.assertEqual(table(self.r(R1))[R4], (3, R2))
        self.assertEqual(table(self.r(R1))[R5], (7, R2))
        self.assertEqual(table(self.r(R2))[R1], (10, R1))       # outra direção não muda
        self.assertTrue(any("ALTERADA" in t for t in self.net.received[R1]))
        with self.assertRaises(CommandError):
            self.r(R1).cmd_cost(R2, 0)

    def test_H_ttl(self):
        # R1 -> R2 -> R4 -> R5: 2 roteadores intermediários
        self.r(R1).cmd_send(R5, "ttl1", ttl=1)
        self.net.deliver()
        self.assertTrue(any("TTL esgotado" in l for l in self.net.logs(R4, "DATA_DESCARTADA")))
        self.assertFalse(self.messages(R5))

        self.r(R1).cmd_send(R5, "ttl0", ttl=0)
        self.net.deliver()
        self.assertTrue(any("TTL esgotado" in l and "ttl0" in l for l in self.net.logs(R2, "DATA_DESCARTADA")))

        self.r(R1).cmd_send(R5, "ttl2", ttl=2)
        self.net.deliver()
        self.assertTrue(any("ttl2" in t for t in self.messages(R5)))
        self.assertTrue(any("ID=3" in l and "TTL=0" in l for l in self.net.logs(R5, "DATA_RECEBIDO")))

    def test_data_no_route(self):
        self.r(R1).cmd_send("10.0.0.99", "oi")
        self.assertTrue(any("sem rota" in l for l in self.net.logs(R1, "DATA_DESCARTADA")))

    def test_del_neighbor(self):
        self.r(R1).cmd_del(R2)
        self.net.deliver()
        self.assertNotIn(R2, self.r(R1).neighbors)
        self.assertEqual(table(self.r(R1))[R2], (14, R3))
        self.assertNotIn(R2, self.read_config(R1))

    def test_seq_saved_before_send(self):
        r1 = self.r(R1)
        self.assertEqual(seqstore.load(r1.seq_path), r1.my_seq)


if __name__ == "__main__":
    unittest.main()
