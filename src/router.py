"""Núcleo do roteador Link State.

A classe Router guarda todo o estado (vizinhos, LSDB, tabela de rotas) e trata:
  - datagramas recebidos ......... handle_datagram()
  - temporizadores ............... tick()   (chamado a cada 0,5 s)
  - comandos do usuário .......... cmd_*()

Ela não conhece sockets: para enviar chama `self.sender(ip, bytes)`, que é
ligado ao socket UDP em main.py (ou a uma rede simulada nos testes). Todo
acesso ao estado passa por `self.lock`, porque três threads usam o roteador
(recepção, temporizadores e linha de comando).
"""

import os
import random
import threading
import time
from dataclasses import dataclass

import config
import protocol
import seqstore
import settings
import views
from dijkstra import compute_routes, diff_routes
from lsdb import LSDB, DUPLICATE, NEW, REFRESHED


class CommandError(Exception):
    """Erro de uso de um comando (mensagem mostrada ao usuário)."""


@dataclass
class Neighbor:
    cost: int                 # custo do enlace de MIM até ele (roteadores.txt)
    enabled: bool = True      # enlace lógico ligado? (comandos down/up)
    active: bool = False      # vizinhança confirmada por HELLO bidirecional?
    last_hello: float = None  # instante do último HELLO válido (monotônico)


class Router:
    def __init__(self, my_ip, neighbors, base_dir=".", logger=None, out=print,
                 clock=time.monotonic, wall_clock=time.time, rng=None,
                 tie_break=None, accept_lsa_from=None, color=False):
        self.my_ip = my_ip
        self.neighbors = {ip: Neighbor(cost) for ip, cost in neighbors.items()}
        self.lsdb = LSDB()
        self.routes = {}                 # destino -> Route
        self.lock = threading.RLock()

        self.config_path = os.path.join(base_dir, settings.CONFIG_FILE)
        self.seq_path = os.path.join(base_dir, settings.SEQ_FILE)
        self.my_seq = seqstore.load(self.seq_path)   # último SEQ usado (0 = nunca)
        self.next_data_id = 1

        self.logger = logger
        self.out = out                   # onde imprimir tabelas/mensagens
        self.clock = clock               # relógio monotônico (temporizadores)
        self.wall_clock = wall_clock     # hora de parede (exibição)
        self.rng = rng or random.Random()
        self.tie_break = tie_break or settings.DESEMPATE
        self.accept_lsa_from = accept_lsa_from or settings.ACEITAR_LSA_DE
        self.color = color
        self.sender = None               # função (ip, bytes) -> None, ligada depois

        self._last_signature = None      # topologia usada no último Dijkstra
        self._next_hello = 0.0
        self._next_lsa = 0.0

    # ------------------------------------------------------------------
    # Inicialização e temporizadores
    # ------------------------------------------------------------------

    def start(self):
        """Gera o primeiro LSA (o que já dispara o primeiro Dijkstra) e envia HELLO."""
        with self.lock:
            self.log("ROTEADOR_INICIADO", self.my_ip,
                     f"vizinhos configurados: {self._configured_list() or 'nenhum'}",
                     f"último SEQ gravado={self.my_seq}")
            self._originate_lsa("inicialização")
            self._send_hellos()
            self._next_hello = self.clock() + settings.HELLO_INTERVAL

    def tick(self):
        """Chamado periodicamente: HELLO (5 s), queda de vizinho (15 s),
        expiração de LSA (30 s) e renovação do LSA local (10 s)."""
        with self.lock:
            now = self.clock()

            if now >= self._next_hello:
                self._send_hellos()
                self._next_hello = now + settings.HELLO_INTERVAL

            for ip, n in list(self.neighbors.items()):
                if n.active and now - n.last_hello > settings.NEIGHBOR_TIMEOUT:
                    self._neighbor_down(ip, f"mais de {settings.NEIGHBOR_TIMEOUT} s sem HELLO")

            expired = self.lsdb.expire(now, settings.LSA_MAX_AGE, keep=self.my_ip)
            for entry in expired:
                self.log("LSA_EXPIRADO", entry.origin, f"SEQ={entry.seq}",
                         f"sem renovação há mais de {settings.LSA_MAX_AGE} s")
                self.log("LSDB_ATUALIZADA", entry.origin, "removido (expirado)")
            if expired:
                self._recompute()

            if now >= self._next_lsa:
                self._originate_lsa("renovação periódica")

    # ------------------------------------------------------------------
    # Recepção
    # ------------------------------------------------------------------

    def handle_datagram(self, data, sender_ip):
        """Ponto de entrada de todo datagrama recebido na porta 6000."""
        with self.lock:
            try:
                text = protocol.decode(data)
                message = protocol.parse(text)
            except protocol.ParseError as e:
                preview = data[:80].decode("utf-8", errors="replace")
                self.log("MSG_DESCARTADA", sender_ip, f"malformada: {e}", repr(preview))
                return

            if isinstance(message, protocol.Hello):
                self._handle_hello(message, sender_ip)
            elif isinstance(message, protocol.Lsa):
                self._handle_lsa(message, text, sender_ip)
            else:
                self._handle_data(message, sender_ip)

    # ---------------------------- HELLO -------------------------------

    def _handle_hello(self, hello, sender_ip):
        if settings.EXIGIR_ORIGEM_HELLO_IGUAL_REMETENTE and hello.origin != sender_ip:
            self.log("HELLO_DESCARTADO", sender_ip, f"IP_ORIGEM {hello.origin} difere do remetente")
            return
        n = self.neighbors.get(hello.origin)
        if n is None:
            self.log("HELLO_DESCARTADO", hello.origin, "não é vizinho configurado")
            return
        if not n.enabled:
            self.log("HELLO_DESCARTADO", hello.origin, "enlace desativado")
            return

        n.last_hello = self.clock()
        # Bidirecional: ele nos tem na lista de vizinhos configurados
        # (e nós o temos, senão teria sido descartado acima).
        two_way = self.my_ip in hello.neighbors
        self.log("HELLO_RECEBIDO", hello.origin, None if two_way else "unidirecional (não nos lista)")

        if two_way and not n.active:
            self._neighbor_up(hello.origin)
        elif not two_way and n.active:
            self._neighbor_down(hello.origin, "vizinho deixou de nos listar no HELLO")

    def _neighbor_up(self, ip):
        self.neighbors[ip].active = True
        self.log("VIZINHO_ATIVO", ip, f"custo {self.neighbors[ip].cost}")
        # HELLO imediato: o outro lado ativa a vizinhança antes de receber nossos
        # LSAs (senão ele os descartaria por virem de vizinho ainda inativo).
        self._send_hello(ip)
        # Novo LSA local (agora com este enlace) – vai para todos os ativos, inclusive ele.
        self._originate_lsa(f"vizinhança com {ip} estabelecida")
        # Sincronização: envia ao novo vizinho todos os outros LSAs válidos da LSDB.
        others = [e for o, e in self.lsdb.entries.items() if o != self.my_ip]
        for entry in others:
            self._send(ip, protocol.format_lsa(entry.origin, entry.seq, entry.links))
        self.log("LSDB_SINCRONIZADA", ip, f"{len(others) + 1} LSAs enviados ao novo vizinho")

    def _neighbor_down(self, ip, reason):
        self.neighbors[ip].active = False
        self.log("VIZINHO_INATIVO", ip, reason)
        self._originate_lsa(f"vizinhança com {ip} perdida")

    # ----------------------------- LSA --------------------------------

    def _handle_lsa(self, lsa, text, sender_ip):
        seq_txt = f"SEQ={lsa.seq}"
        n = self.neighbors.get(sender_ip)
        if n is None:
            return self._drop_lsa(lsa, f"recebido de {sender_ip}, que não é vizinho configurado")
        if not n.enabled:
            return self._drop_lsa(lsa, f"enlace com {sender_ip} desativado")
        if self.accept_lsa_from == "ativo" and not n.active:
            return self._drop_lsa(lsa, f"recebido de {sender_ip}, que não é vizinho ativo")

        if lsa.origin == self.my_ip:
            if settings.SALTAR_SEQ_PROPRIA and lsa.seq > self.my_seq:
                self.log("SEQ_SALTADA", self.my_ip, f"recebido próprio LSA {seq_txt} > {self.my_seq}")
                self.my_seq = lsa.seq
                self._originate_lsa("salto de sequência")
            return self._drop_lsa(lsa, f"LSA com o próprio IP de origem (via {sender_ip})")

        status = self.lsdb.check(lsa.origin, lsa.seq)
        if status != NEW:
            last = self.lsdb.max_seq[lsa.origin]
            what = "duplicado" if status == DUPLICATE else "antigo"
            return self._drop_lsa(lsa, f"{what} (maior SEQ aceito={last}) via {sender_ip}")

        change = self.lsdb.install(lsa.origin, lsa.seq, lsa.links, self.clock(), self.wall_clock())
        self.log("LSA_ACEITO", lsa.origin, seq_txt, f"via {sender_ip}", text)
        if change != REFRESHED:
            self.log("LSDB_ATUALIZADA", lsa.origin, change)

        # Flooding: repassa o datagrama original a todos os ativos, menos quem enviou.
        targets = [ip for ip in self._active() if ip != sender_ip]
        for ip in targets:
            self._send(ip, text)
        if targets:
            self.log("LSA_ENCAMINHADO", lsa.origin, seq_txt, "para " + ", ".join(targets))

        self._recompute()

    def _drop_lsa(self, lsa, reason):
        self.log("LSA_DESCARTADO", lsa.origin, f"SEQ={lsa.seq}", reason)

    # ----------------------------- DATA -------------------------------

    def _handle_data(self, data, sender_ip):
        if data.dest == self.my_ip:
            self._deliver(data)
        else:
            self._forward(data, originated_here=False)

    def _deliver(self, data):
        self.log("DATA_RECEBIDO", f"ID={data.msg_id}", f"DESTINO {data.dest}",
                 f"ORIGEM {data.origin}", f"TTL={data.ttl}", data.text)
        self.out(f"\n>>> Mensagem de {data.origin} (ID {data.msg_id}): {data.text}\n")

    def _forward(self, data, originated_here):
        """Encaminha DATA pelo próximo salto da tabela.

        A origem envia com o TTL inicial sem decrementar. Um roteador
        intermediário descarta se TTL == 0; senão decrementa e encaminha.
        """
        ident = (f"ID={data.msg_id}", f"DESTINO {data.dest}", f"ORIGEM {data.origin}")
        route = self.routes.get(data.dest)
        if route is None or not self._is_active(route.next_hop):
            self.log("DATA_DESCARTADA", *ident, "motivo: sem rota", data.text)
            return False

        ttl = data.ttl
        if not originated_here:
            if ttl == 0:
                self.log("DATA_DESCARTADA", *ident, "motivo: TTL esgotado (TTL=0)", data.text)
                return False
            ttl -= 1

        text = protocol.format_data(data.origin, data.dest, data.msg_id, ttl, data.text)
        self._send(route.next_hop, text)
        event = "DATA_ENVIADA" if originated_here else "DATA_ENCAMINHADA"
        self.log(event, *ident, f"PRÓXIMO SALTO {route.next_hop}", f"TTL={ttl}", data.text)
        return True

    # ------------------------------------------------------------------
    # LSA local e cálculo de rotas
    # ------------------------------------------------------------------

    def _originate_lsa(self, reason):
        """Cria um novo LSA local (SEQ+1), grava o SEQ, envia aos ativos e recalcula."""
        seq = self.my_seq + 1
        if seq > settings.MAX_SEQ:
            self.log("ERRO", self.my_ip, "número de sequência esgotado")
            return
        seqstore.save(self.seq_path, seq)        # grava ANTES de enviar
        self.my_seq = seq

        links = {ip: n.cost for ip, n in self.neighbors.items() if n.active}
        change = self.lsdb.install(self.my_ip, seq, links, self.clock(), self.wall_clock())
        text = protocol.format_lsa(self.my_ip, seq, links)
        self.log("LSA_GERADO", self.my_ip, f"SEQ={seq}", reason, text)
        if change != REFRESHED:
            self.log("LSDB_ATUALIZADA", self.my_ip, f"LSA local: {change}")

        for ip in self._active():
            self._send(ip, text)
        self._next_lsa = self.clock() + settings.LSA_INTERVAL
        self._recompute()

    def _recompute(self):
        """Roda o Dijkstra só se a topologia (enlaces e custos) mudou."""
        signature = self.lsdb.signature()
        if signature == self._last_signature:
            return
        self._last_signature = signature

        new_routes = compute_routes(self.lsdb.topology(), self.my_ip, set(self._active()),
                                    self.tie_break, self.rng, previous=self.routes)
        self.log("DIJKSTRA_EXECUTADO", f"{len(self.lsdb.entries)} nós na LSDB",
                 f"{len(new_routes)} rotas")
        changes = diff_routes(self.routes, new_routes)
        self.routes = new_routes

        for kind, dest, old, new in changes:
            if kind == "NOVA":
                self.log("ROTA_NOVA", dest, f"custo {new.cost} via {new.next_hop}")
            elif kind == "REMOVIDA":
                self.log("ROTA_REMOVIDA", dest, f"era custo {old.cost} via {old.next_hop}")
            else:
                self.log("ROTA_ALTERADA", dest, f"custo {old.cost}->{new.cost}",
                         f"via {old.next_hop}->{new.next_hop}")
        if changes:
            self.out(views.format_routes(self.routes, changes, self.color))

    # ------------------------------------------------------------------
    # Envio
    # ------------------------------------------------------------------

    def _send(self, ip, text):
        try:
            data = protocol.encode(text)
        except ValueError as e:
            self.log("ERRO_ENVIO", ip, str(e))
            return
        try:
            self.sender(ip, data)
        except OSError as e:
            self.log("ERRO_ENVIO", ip, str(e))

    def _send_hello(self, ip):
        self._send(ip, protocol.format_hello(self.my_ip, self._configured_list()))
        self.log("HELLO_ENVIADO", ip)

    def _send_hellos(self):
        for ip, n in self.neighbors.items():
            if n.enabled:
                self._send_hello(ip)

    # ------------------------------------------------------------------
    # Comandos do usuário
    # ------------------------------------------------------------------

    def cmd_send(self, dest, text, ttl=settings.DEFAULT_TTL):
        """Envia uma mensagem DATA. Retorna o ID usado."""
        with self.lock:
            if not protocol.is_ipv4(dest):
                raise CommandError(f"IP inválido: {dest}")
            if not settings.MIN_TTL <= ttl <= settings.MAX_TTL:
                raise CommandError(f"TTL deve estar entre {settings.MIN_TTL} e {settings.MAX_TTL}")
            msg_id = self.next_data_id
            try:
                protocol.encode(protocol.format_data(self.my_ip, dest, msg_id, ttl, text))
            except ValueError as e:
                raise CommandError(str(e)) from None
            self.next_data_id += 1

            data = protocol.Data(self.my_ip, dest, msg_id, ttl, text)
            if dest == self.my_ip:
                self._deliver(data)
            else:
                self._forward(data, originated_here=True)
            return msg_id

    def cmd_down(self, ip):
        """Desativa o enlace lógico: para de enviar HELLO e descarta HELLO/LSA dele."""
        with self.lock:
            n = self._neighbor(ip)
            if not n.enabled:
                raise CommandError(f"enlace com {ip} já está desativado")
            n.enabled = False
            self.log("ENLACE_DESATIVADO", ip, "comando do usuário")
            if n.active:
                self._neighbor_down(ip, "enlace desativado pelo usuário")

    def cmd_up(self, ip):
        """Reativa o enlace: volta a enviar HELLO; só fica ativo após HELLO válido."""
        with self.lock:
            n = self._neighbor(ip)
            if n.enabled:
                raise CommandError(f"enlace com {ip} já está ativado")
            n.enabled = True
            n.last_hello = None
            self.log("ENLACE_ATIVADO", ip, "aguardando HELLO para confirmar a vizinhança")
            self._send_hello(ip)

    def cmd_cost(self, ip, cost):
        with self.lock:
            n = self._neighbor(ip)
            self._check_cost(cost)
            if n.cost == cost:
                raise CommandError(f"custo para {ip} já é {cost}")
            old, n.cost = n.cost, cost
            self._save_config()
            self.log("CUSTO_ALTERADO", ip, f"{old} -> {cost}")
            if n.active:
                self._originate_lsa(f"custo para {ip} alterado")

    def cmd_add(self, ip, cost):
        with self.lock:
            if not protocol.is_ipv4(ip):
                raise CommandError(f"IP inválido: {ip}")
            if ip == self.my_ip:
                raise CommandError("o próprio IP não pode ser vizinho")
            if ip in self.neighbors:
                raise CommandError(f"{ip} já é vizinho (use o comando custo)")
            self._check_cost(cost)
            self.neighbors[ip] = Neighbor(cost)
            self._save_config()
            self.log("VIZINHO_ADICIONADO", ip, f"custo {cost}",
                     "fica ativo quando o outro lado também o configurar")
            self._send_hello(ip)

    def cmd_del(self, ip):
        with self.lock:
            n = self._neighbor(ip)
            del self.neighbors[ip]
            self._save_config()
            self.log("VIZINHO_REMOVIDO", ip)
            if n.active:
                self._originate_lsa(f"vizinho {ip} removido")

    def cmd_replay(self, neighbor, origin, mode, seq=None):
        """Teste: reenvia ao vizinho o LSA armazenado de `origin` com o SEQ
        original ("dup") ou com um SEQ menor ("old"). Retorna o texto enviado."""
        with self.lock:
            self._neighbor(neighbor)
            entry = self.lsdb.get(origin)
            if entry is None:
                raise CommandError(f"não há LSA de {origin} na LSDB")
            if mode == "dup":
                send_seq = entry.seq
            elif mode == "old":
                send_seq = entry.seq - 1 if seq is None else seq
                if not settings.MIN_SEQ <= send_seq < entry.seq:
                    raise CommandError(f"SEQ antigo deve estar entre 1 e {entry.seq - 1}")
            else:
                raise CommandError("modo deve ser dup ou old")
            text = protocol.format_lsa(origin, send_seq, entry.links)
            self._send(neighbor, text)
            label = "duplicado" if mode == "dup" else "antigo"
            self.log("LSA_REENVIADO_TESTE", origin, f"SEQ={send_seq}", label, f"para {neighbor}", text)
            return text

    # ------------------------------------------------------------------
    # Consultas (exibição)
    # ------------------------------------------------------------------

    def show_lsdb(self):
        with self.lock:
            return views.format_lsdb(self)

    def show_routes(self):
        with self.lock:
            return views.format_routes(self.routes, None, self.color)

    def show_neighbors(self):
        with self.lock:
            return views.format_neighbors(self)

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------

    def log(self, event, *fields):
        if self.logger:
            self.logger.log(event, *fields)

    def _active(self):
        return [ip for ip, n in self.neighbors.items() if n.active]

    def _is_active(self, ip):
        n = self.neighbors.get(ip)
        return n is not None and n.active

    def _configured_list(self):
        return sorted(self.neighbors, key=protocol.ip_key)

    def _neighbor(self, ip):
        n = self.neighbors.get(ip)
        if n is None:
            raise CommandError(f"{ip} não é vizinho configurado")
        return n

    @staticmethod
    def _check_cost(cost):
        if not settings.MIN_COST <= cost <= settings.MAX_COST:
            raise CommandError(f"custo deve estar entre {settings.MIN_COST} e {settings.MAX_COST}")

    def _save_config(self):
        config.save_neighbors(self.config_path, {ip: n.cost for ip, n in self.neighbors.items()})
