#!/usr/bin/env python3
"""Executa os cenários A–H do relatório numa máquina só, com captura do Wireshark.

Cada roteador é um processo real (src/main.py) com socket UDP na porta 6000.
Os IPs 192.168.1.N da topologia viram 127.0.0.N (loopback), então antes é
preciso criar os aliases (sudo bash scripts/preparar_mac.sh).

A captura é feita pelo dumpcap (Wireshark) na interface de loopback, um
arquivo .pcapng por cenário em capturas/. Tudo o que aparece nos terminais
(tabelas, LSDB, vizinhos) e os logs de cada roteador vão para resultados/.

Uso:
    python3 scripts/cenarios.py              # roda tudo (~3 min)
    python3 scripts/cenarios.py --sem-captura
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "src", "main.py")
TOPO = os.path.join(ROOT, "topologia")
RUN_DIR = os.path.join(ROOT, "resultados", "roteadores")   # pastas de execução (seq.txt, log)
OUT_DIR = os.path.join(ROOT, "resultados")
CAP_DIR = os.path.join(ROOT, "capturas")

DUMPCAP_CANDIDATES = [
    "/Applications/Wireshark.app/Contents/MacOS/dumpcap",
    shutil.which("dumpcap") or "",
]
LOOPBACK_IF = "lo0" if sys.platform == "darwin" else "lo"


def ip(n):
    return f"127.0.0.{n}"


def can_bind(addr):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.bind((addr, 0))
            return True
        except OSError:
            return False


def now():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class Node:
    """Um roteador rodando como processo, controlado pela entrada padrão."""

    def __init__(self, n):
        self.n = n
        self.name = f"R{n}"
        self.ip = ip(n)
        self.dir = os.path.join(RUN_DIR, f"r{n}")
        self.out_path = os.path.join(self.dir, "terminal.txt")
        self.proc = None
        self.out = None

    def prepare(self):
        """Copia o roteadores.txt da topologia trocando 192.168.1.N por 127.0.0.N."""
        os.makedirs(self.dir, exist_ok=True)
        for f in ("seq.txt", "router.log", "terminal.txt"):
            p = os.path.join(self.dir, f)
            if os.path.exists(p):
                os.remove(p)
        with open(os.path.join(TOPO, f"r{self.n}", "roteadores.txt"), encoding="utf-8") as src:
            text = src.read().replace("192.168.1.", "127.0.0.")
        with open(os.path.join(self.dir, "roteadores.txt"), "w", encoding="utf-8") as dst:
            dst.write(text)

    def start(self):
        env = dict(os.environ, NO_COLOR="1", PYTHONUNBUFFERED="1")
        self.out = open(self.out_path, "a", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-u", MAIN, "--ip", self.ip, "--dir", self.dir, "--log-tela", "sem-hello"],
            stdin=subprocess.PIPE, stdout=self.out, stderr=subprocess.STDOUT, text=True, env=env)
        timeline(f"{self.name} ({self.ip}) iniciado")

    def cmd(self, line, quiet=False):
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        if not quiet:
            timeline(f"{self.name}> {line}")

    def query(self, line):
        """Executa um comando de consulta e devolve só o que ele imprimiu."""
        self.out.flush()
        start = os.path.getsize(self.out_path)
        self.cmd(line, quiet=True)
        time.sleep(0.4)
        with open(self.out_path, encoding="utf-8") as f:
            f.seek(start)
            text = f.read()
        # tira os prompts "> " e linhas de log que caíram no meio
        lines = [l[2:] if l.startswith("> ") else l for l in text.splitlines()]
        lines = [l for l in lines if not re.match(r"^\d\d:\d\d:\d\d\.\d{3} \|", l)]
        return "\n".join(lines).strip("\n") + "\n"

    def kill(self):
        """Falha do roteador: Ctrl+C no processo."""
        self.proc.send_signal(signal.SIGINT)
        self.proc.wait(timeout=5)
        self.out.close()
        timeline(f"{self.name} ({self.ip}) encerrado com Ctrl+C (falha do roteador)")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.cmd("sair", quiet=True)
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
        if self.out and not self.out.closed:
            self.out.close()


# ---------------------------------------------------------------------------
# Registro (cronologia, snapshots, recortes de log)
# ---------------------------------------------------------------------------

TIMELINE = []
SCENARIOS = []      # [{id, titulo, inicio, fim, captura}]
CURRENT = {}


def timeline(text):
    line = f"{now()}  {text}"
    TIMELINE.append(line)
    if CURRENT:
        CURRENT["eventos"].append(line)
    print(line, flush=True)


def snapshot(label, nodes, *what):
    """Grava a saída de lsdb/rotas/vizinhos de cada roteador no cenário atual."""
    folder = os.path.join(OUT_DIR, CURRENT["id"])
    os.makedirs(folder, exist_ok=True)
    for node in nodes:
        parts = []
        for w in what:
            parts.append(f"$ {w}\n{node.query(w)}")
        path = os.path.join(folder, f"{label}_{node.name}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# {CURRENT['id']} – {label} – {node.name} ({node.ip}) – {now()}\n")
            f.write("\n".join(parts))
    timeline(f"[snapshot {label}: {', '.join(n.name for n in nodes)} – {', '.join(what)}]")


class Capture:
    def __init__(self, enabled):
        self.enabled = enabled
        self.proc = None
        self.dumpcap = next((p for p in DUMPCAP_CANDIDATES if p and os.path.exists(p)), None)

    def check(self):
        if not self.enabled:
            return
        if not self.dumpcap:
            sys.exit("dumpcap não encontrado (instale o Wireshark) ou use --sem-captura")
        # captura de teste de 1 s: falha se não houver permissão no BPF
        test = os.path.join(CAP_DIR, ".teste.pcapng")
        r = subprocess.run([self.dumpcap, "-i", LOOPBACK_IF, "-a", "duration:1", "-q", "-w", test],
                           capture_output=True, text=True)
        if os.path.exists(test):
            os.remove(test)
        if r.returncode != 0:
            sys.exit("dumpcap não consegue capturar (rode antes: sudo bash scripts/preparar_mac.sh)\n"
                     + r.stderr)

    def start(self, path):
        if not self.enabled:
            return
        self.proc = subprocess.Popen(
            [self.dumpcap, "-i", LOOPBACK_IF, "-f", "udp port 6000", "-q", "-w", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        time.sleep(1.5)
        if self.proc.poll() is not None:
            sys.exit("dumpcap falhou: " + self.proc.stderr.read())

    def stop(self):
        if self.proc:
            time.sleep(0.5)
            self.proc.send_signal(signal.SIGINT)
            self.proc.wait(timeout=10)
            self.proc = None


def begin(cid, title, cap, slug):
    CURRENT.clear()
    CURRENT.update(id=cid, titulo=title, inicio=now(), eventos=[],
                   captura=f"capturas/{cid}_{slug}.pcapng" if cap.enabled else None)
    os.makedirs(os.path.join(OUT_DIR, cid), exist_ok=True)
    if cap.enabled:
        cap.start(os.path.join(ROOT, CURRENT["captura"]))
    timeline(f"=== Cenário {cid}: {title} ===")


def end(cap):
    cap.stop()
    CURRENT["fim"] = now()
    SCENARIOS.append(dict(CURRENT))
    timeline(f"=== fim do cenário {CURRENT['id']} ===")
    CURRENT.clear()


def wait(seconds, why=""):
    if why:
        timeline(f"(aguardando {seconds} s: {why})")
    time.sleep(seconds)


def cut_logs(nodes):
    """Separa o router.log de cada roteador por cenário (resultados/<X>/logs/Rn.log)."""
    for sc in SCENARIOS:
        folder = os.path.join(OUT_DIR, sc["id"], "logs")
        os.makedirs(folder, exist_ok=True)
        for node in nodes:
            path = os.path.join(node.dir, "router.log")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                lines = [l for l in f if sc["inicio"] <= l[:12] <= sc["fim"]]
            if lines:
                with open(os.path.join(folder, f"{node.name}.log"), "w", encoding="utf-8") as out:
                    out.writelines(lines)


# ---------------------------------------------------------------------------
# Cenários
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sem-captura", action="store_true", help="não captura com o dumpcap")
    args = ap.parse_args()

    os.makedirs(CAP_DIR, exist_ok=True)
    missing = [ip(n) for n in range(1, 7) if not can_bind(ip(n))]
    if missing:
        sys.exit("Sem os IPs de loopback " + ", ".join(missing)
                 + " (rode antes: sudo bash scripts/preparar_mac.sh)")
    cap = Capture(not args.sem_captura)
    cap.check()
    for d in "ABCDEFGH":
        shutil.rmtree(os.path.join(OUT_DIR, d), ignore_errors=True)

    R = {n: Node(n) for n in range(1, 7)}
    for node in R.values():
        node.prepare()
    core = [R[n] for n in range(1, 6)]
    alive = []

    try:
        # A – convergência inicial: R1..R5 (R6 fica de fora até o cenário B)
        begin("A", "Convergência inicial da rede", cap, "convergencia")
        for node in core:
            node.start()
            alive.append(node)
            time.sleep(0.3)
        wait(4, "primeiros HELLOs e LSAs")
        snapshot("t04s", core, "vizinhos", "rotas")
        wait(18, "renovações periódicas sem mudança de topologia")
        snapshot("convergida", core, "vizinhos", "lsdb", "rotas")
        end(cap)

        # B – entrada de um novo roteador (R6, vizinho de R4 e R5)
        begin("B", "Entrada de um novo roteador", cap, "novo_roteador")
        R[6].start()
        alive.append(R[6])
        wait(7, "R6 envia HELLO, mas R4 e R5 ainda não o têm configurado")
        snapshot("antes_add", [R[6], R[4]], "vizinhos", "lsdb")
        R[4].cmd(f"add {ip(6)} 6")
        R[5].cmd(f"add {ip(6)} 3")
        wait(8, "vizinhanças R4–R6 e R5–R6 e sincronização da LSDB de R6")
        snapshot("depois_add", list(R.values()), "rotas")
        snapshot("depois_add_lsdb", [R[6]], "vizinhos", "lsdb")
        end(cap)

        # C – falha de um enlace (R2–R4) e restauração
        begin("C", "Falha de um enlace", cap, "falha_enlace")
        snapshot("antes", [R[1], R[2], R[4]], "rotas")
        R[2].cmd(f"down {ip(4)}")
        wait(3, "R2 derruba o enlace na hora; R4 ainda não percebeu")
        snapshot("t03s", [R[2], R[4]], "vizinhos")
        snapshot("t03s_rotas", [R[1], R[2]], "rotas")
        wait(16, "R4 detecta a falta de HELLO após 15 s")
        snapshot("t19s", [R[4]], "vizinhos")
        snapshot("t19s_rotas", [R[1], R[2], R[4]], "rotas")
        snapshot("t19s_lsdb", [R[1]], "lsdb")
        R[2].cmd(f"up {ip(4)}")
        wait(8, "enlace volta só depois de HELLO válido nos dois sentidos")
        snapshot("depois_up", [R[1], R[2], R[4]], "vizinhos", "rotas")
        end(cap)

        # D – falha de um roteador (R4)
        begin("D", "Falha de um roteador", cap, "falha_roteador")
        snapshot("antes", [R[1], R[2], R[6]], "rotas")
        R[4].kill()
        alive.remove(R[4])
        wait(5, "LSA de R4 ainda válido; vizinhos ainda não detectaram")
        snapshot("t05s", [R[1]], "rotas", "lsdb")
        wait(14, "R2, R3, R5 e R6 detectam a falta de HELLO (15 s)")
        snapshot("t19s", [R[1], R[2], R[3], R[5], R[6]], "rotas")
        snapshot("t19s_lsdb", [R[1]], "lsdb")
        wait(15, "LSA de R4 expira (30 s sem renovação)")
        snapshot("t34s", [R[1]], "lsdb", "rotas")
        end(cap)

        # E – recuperação: R4 reinicia e continua a sequência do seq.txt
        begin("E", "Recuperação após falha", cap, "recuperacao")
        with open(os.path.join(R[4].dir, "seq.txt"), encoding="utf-8") as f:
            timeline(f"seq.txt de R4 antes de reiniciar = {f.read().strip()}")
        R[4].start()
        alive.append(R[4])
        wait(10, "R4 forma vizinhanças, recebe a LSDB e anuncia o novo LSA")
        snapshot("depois", [R[4]], "vizinhos", "lsdb", "rotas")
        snapshot("depois_rotas", [R[1], R[2], R[6]], "rotas")
        end(cap)

        # F – LSAs antigos e duplicados (comando replay em R1, para R2)
        begin("F", "Recebimento de LSAs antigos e duplicados", cap, "lsa_antigo_duplicado")
        snapshot("antes", [R[2]], "lsdb")
        R[1].cmd(f"replay {ip(2)} {ip(5)} dup")
        time.sleep(1)
        R[1].cmd(f"replay {ip(2)} {ip(5)} old")
        time.sleep(1)
        R[1].cmd(f"replay {ip(2)} {ip(5)} old 1")
        time.sleep(1)
        R[1].cmd(f"replay {ip(2)} {ip(1)} dup")
        time.sleep(1)
        snapshot("depois", [R[2]], "lsdb")
        end(cap)

        # G – alteração do custo do enlace R1->R2 (10 -> 1)
        begin("G", "Alteração do custo de um enlace", cap, "custo")
        snapshot("antes", [R[1], R[2]], "rotas")
        R[1].cmd(f"custo {ip(2)} 1")
        wait(3, "LSA imediato de R1 e novo Dijkstra em todos")
        snapshot("depois", [R[1], R[2], R[5]], "rotas")
        snapshot("depois_lsdb", [R[2]], "lsdb")
        end(cap)

        # H – DATA com TTL insuficiente (R1 -> R5 passa por R2 e R4: 2 intermediários)
        begin("H", "Encaminhamento de DATA com TTL insuficiente", cap, "ttl")
        snapshot("rotas", [R[1], R[2], R[4]], "rotas")
        R[1].cmd(f"send {ip(5)} ttl=0 teste TTL 0")
        time.sleep(1)
        R[1].cmd(f"send {ip(5)} ttl=1 teste TTL 1")
        time.sleep(1)
        R[1].cmd(f"send {ip(5)} ttl=2 teste TTL 2")
        time.sleep(1)
        R[1].cmd(f"send {ip(5)} Olá R5, TTL padrão; com ponto e vírgula")
        time.sleep(1)
        R[1].cmd(f"send {ip(9)} ttl=5 destino que não existe")
        time.sleep(1.5)
        end(cap)
    finally:
        for node in alive:
            node.stop()

    cut_logs(list(R.values()))
    with open(os.path.join(OUT_DIR, "cronologia.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(TIMELINE) + "\n")
    with open(os.path.join(OUT_DIR, "cenarios.json"), "w", encoding="utf-8") as f:
        json.dump(SCENARIOS, f, ensure_ascii=False, indent=2)
    print(f"\nPronto. Resultados em {OUT_DIR}" + (f", capturas em {CAP_DIR}" if cap.enabled else ""))


if __name__ == "__main__":
    main()
