"""Rede simulada para testar vários roteadores sem sockets e sem esperar o relógio.

Cada roteador real (classe Router) recebe um `sender` que coloca o datagrama
numa fila; `advance()` avança o relógio falso, chama tick() de todos e entrega
as mensagens na ordem em que foram enviadas.
"""

import os
import random
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
from logger import Logger  # noqa: E402
from router import Router  # noqa: E402


class SimNet:
    def __init__(self, base_dir, tie_break="menor_ip"):
        self.base_dir = base_dir
        self.tie_break = tie_break
        self.now = 1000.0
        self.routers = {}
        self.alive = set()
        self.cut = set()          # pares (a, b) com o "cabo" desligado
        self.queue = deque()
        self.sent = []            # histórico (origem, destino, texto)
        self.received = {}        # ip -> mensagens DATA exibidas

    def clock(self):
        return self.now

    def add(self, ip, neighbors, start=True):
        folder = os.path.join(self.base_dir, ip)
        os.makedirs(folder, exist_ok=True)
        config.save_neighbors(os.path.join(folder, "roteadores.txt"), neighbors)
        loaded = config.load_neighbors(os.path.join(folder, "roteadores.txt"), ip)
        self.received.setdefault(ip, [])
        router = Router(ip, loaded, base_dir=folder, logger=Logger(None, screen="nada"),
                        out=lambda text, ip=ip: self.received[ip].append(text),
                        clock=self.clock, wall_clock=lambda: 0.0,
                        rng=random.Random(1), tie_break=self.tie_break)
        router.sender = lambda dst, data, src=ip: self._enqueue(src, dst, data)
        self.routers[ip] = router
        if start:
            self.start(ip)
        return router

    def start(self, ip):
        self.alive.add(ip)
        self.routers[ip].start()
        self.deliver()

    def crash(self, ip):
        self.alive.discard(ip)

    def restart(self, ip):
        """Novo processo na mesma pasta (relê roteadores.txt e seq.txt)."""
        folder = os.path.join(self.base_dir, ip)
        neighbors = config.load_neighbors(os.path.join(folder, "roteadores.txt"), ip)
        return self.add(ip, neighbors)

    def inject(self, src, dst, text):
        self._enqueue(src, dst, text.encode("utf-8"))
        self.deliver()

    def _enqueue(self, src, dst, data):
        self.queue.append((src, dst, data))

    def deliver(self):
        while self.queue:
            src, dst, data = self.queue.popleft()
            if src not in self.alive or dst not in self.alive:
                continue
            if (src, dst) in self.cut or (dst, src) in self.cut:
                continue
            self.sent.append((src, dst, data.decode("utf-8", errors="replace")))
            self.routers[dst].handle_datagram(data, src)

    def advance(self, seconds, step=0.5):
        end = self.now + seconds
        while self.now < end:
            self.now += step
            for ip in sorted(self.alive):
                self.routers[ip].tick()
            self.deliver()

    def logs(self, ip, event=None):
        lines = self.routers[ip].logger.lines
        return [l for l in lines if event is None or f"| {event} |" in l or l.endswith(f"| {event}")]

    def clear_logs(self):
        for r in self.routers.values():
            r.logger.lines.clear()
        self.sent.clear()
