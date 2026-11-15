"""Ponto de entrada: inicia o roteador e a linha de comando.

Uso:
    python src/main.py --ip 192.168.1.1 [--dir pasta] [--log-tela tudo|sem-hello|nada]

A pasta (--dir, padrão: a atual) contém roteadores.txt, seq.txt e router.log.
"""

import argparse
import os
import socket
import sys
import threading
import time

import config
import settings
from logger import Logger, SCREEN_LEVELS
from router import CommandError, Router
from transport import UdpTransport

HELP = f"""
Comandos:
  lsdb                               mostra a LSDB
  rotas                              mostra a tabela de roteamento
  vizinhos                           mostra os vizinhos e o estado de cada enlace
  down <ip>                          desativa o enlace lógico com o vizinho
  up <ip>                            reativa o enlace lógico (volta após HELLO)
  custo <ip> <custo>                 altera o custo do enlace (grava roteadores.txt)
  add <ip> <custo>                   adiciona vizinho (grava roteadores.txt)
  del <ip>                           remove vizinho (grava roteadores.txt)
  send <ip> [ttl=N] <mensagem>       envia DATA (TTL {settings.MIN_TTL}-{settings.MAX_TTL}, padrão {settings.DEFAULT_TTL})
  replay <vizinho> <origem> dup      reenvia ao vizinho o LSA de <origem> com o mesmo SEQ
  replay <vizinho> <origem> old [s]  idem com SEQ menor (padrão SEQ-1)
  log tudo|sem-hello|nada            o que aparece do log nesta tela (arquivo sempre completo)
  help                               esta ajuda
  sair                               encerra o roteador
"""

ALIASES = {
    "tabela": "rotas", "routes": "rotas", "neighbors": "vizinhos",
    "desativar": "down", "ativar": "up", "cost": "custo",
    "adicionar": "add", "remover": "del", "enviar": "send", "reenviar": "replay",
    "ajuda": "help", "?": "help", "exit": "sair", "quit": "sair",
}


def detect_ip(neighbors):
    """Descobre o IP local da interface usada para chegar ao 1º vizinho
    (connect em UDP não envia nada, só escolhe a rota)."""
    target = next(iter(neighbors), "8.8.8.8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect((target, settings.PORT))
            return s.getsockname()[0]
        except OSError:
            return None


def parse_int(text, what):
    try:
        return int(text)
    except ValueError:
        raise CommandError(f"{what} deve ser um inteiro: {text!r}") from None


def run_command(router, logger, line):
    """Executa uma linha digitada. Retorna False para encerrar."""
    parts = line.split()
    if not parts:
        return True
    cmd = ALIASES.get(parts[0].lower(), parts[0].lower())
    args = parts[1:]

    def need(n, usage):
        if len(args) < n:
            raise CommandError(f"uso: {usage}")

    if cmd == "lsdb":
        print(router.show_lsdb())
    elif cmd == "rotas":
        print(router.show_routes())
    elif cmd == "vizinhos":
        print(router.show_neighbors())
    elif cmd == "down":
        need(1, "down <ip>")
        router.cmd_down(args[0])
    elif cmd == "up":
        need(1, "up <ip>")
        router.cmd_up(args[0])
    elif cmd == "custo":
        need(2, "custo <ip> <custo>")
        router.cmd_cost(args[0], parse_int(args[1], "custo"))
    elif cmd == "add":
        need(2, "add <ip> <custo>")
        router.cmd_add(args[0], parse_int(args[1], "custo"))
    elif cmd == "del":
        need(1, "del <ip>")
        router.cmd_del(args[0])
    elif cmd == "send":
        # o texto pode ter espaços: separa só destino e (opcional) ttl=N
        rest = line.split(maxsplit=2)
        if len(rest) < 3:
            raise CommandError("uso: send <ip> [ttl=N] <mensagem>")
        dest, text = rest[1], rest[2]
        ttl = settings.DEFAULT_TTL
        if text.lower().startswith("ttl="):
            ttl_token, _, text = text.partition(" ")
            ttl = parse_int(ttl_token[4:], "TTL")
            if not text:
                raise CommandError("mensagem vazia")
        msg_id = router.cmd_send(dest, text, ttl)
        print(f"DATA ID={msg_id} para {dest} com TTL={ttl}")
    elif cmd == "replay":
        need(3, "replay <vizinho> <origem> dup|old [seq]")
        seq = parse_int(args[3], "SEQ") if len(args) > 3 else None
        text = router.cmd_replay(args[0], args[1], args[2].lower(), seq)
        print(f"Reenviado para {args[0]}: {text}")
    elif cmd == "log":
        need(1, "log tudo|sem-hello|nada")
        if args[0] not in SCREEN_LEVELS:
            raise CommandError("uso: log tudo|sem-hello|nada")
        logger.screen = args[0]
        print(f"Log na tela: {args[0]}")
    elif cmd == "help":
        print(HELP)
    elif cmd == "sair":
        return False
    else:
        raise CommandError(f"comando desconhecido: {parts[0]} (digite help)")
    return True


def main():
    ap = argparse.ArgumentParser(description="Roteador Link State (inspirado no OSPF) – UDP 6000")
    ap.add_argument("--ip", help="IPv4 deste roteador (padrão: detecta pela rota até o 1º vizinho)")
    ap.add_argument("--dir", default=".", help="pasta com roteadores.txt, seq.txt e router.log")
    ap.add_argument("--log-tela", choices=SCREEN_LEVELS, default="sem-hello",
                    help="eventos de log exibidos no terminal (o arquivo é sempre completo)")
    args = ap.parse_args()

    if os.name == "nt":
        os.system("")  # habilita cores ANSI no terminal do Windows

    base_dir = os.path.abspath(args.dir)
    neighbors = config.load_neighbors(os.path.join(base_dir, settings.CONFIG_FILE), args.ip)
    my_ip = args.ip or detect_ip(neighbors)
    if not my_ip:
        sys.exit("Não foi possível detectar o IP; use --ip.")
    neighbors.pop(my_ip, None)

    logger = Logger(os.path.join(base_dir, settings.LOG_FILE), screen=args.log_tela)
    router = Router(my_ip, neighbors, base_dir=base_dir, logger=logger,
                    color=sys.stdout.isatty() and "NO_COLOR" not in os.environ)
    try:
        transport = UdpTransport(my_ip, router.handle_datagram,
                                 on_error=lambda msg: logger.log("ERRO", msg))
    except OSError as e:
        sys.exit(f"Não foi possível abrir UDP {my_ip}:{settings.PORT}: {e}")
    router.sender = transport.send

    print(f"Roteador {my_ip} – UDP {settings.PORT} – pasta {base_dir}")
    print(f"Log completo em {os.path.join(base_dir, settings.LOG_FILE)}. Digite help para os comandos.")
    transport.start()
    router.start()

    def timer_loop():
        while True:
            time.sleep(settings.TICK_INTERVAL)
            try:
                router.tick()
            except Exception as e:  # não deixa a thread de temporizadores morrer
                logger.log("ERRO", f"temporizador: {e!r}")

    threading.Thread(target=timer_loop, name="temporizadores", daemon=True).start()

    try:
        while True:
            try:
                line = input("> ")
            except EOFError:
                # sem terminal (ex.: rodando em segundo plano): continua sem CLI
                print("Entrada fechada; roteador segue rodando (Ctrl+C para sair).")
                while True:
                    time.sleep(3600)
            try:
                if not run_command(router, logger, line):
                    break
            except CommandError as e:
                print(f"Erro: {e}")
    except KeyboardInterrupt:
        print()
    finally:
        logger.log("ROTEADOR_ENCERRADO", my_ip)
        transport.close()
        logger.close()


if __name__ == "__main__":
    main()
