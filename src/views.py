"""Formatação das tabelas mostradas no terminal (LSDB, rotas, vizinhos)."""

from datetime import datetime

import settings
from protocol import ip_key

# Cores ANSI para destacar mudanças de rota (desligadas se a saída não é um terminal)
GREEN, RED, YELLOW, BOLD, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"


def _paint(text, color, enabled):
    return f"{color}{text}{RESET}" if enabled else text


def format_routes(routes, changes=None, color=False):
    """Tabela Destino / Custo total / Próximo salto.

    Com `changes` (saída de diff_routes), marca as linhas novas/alteradas e
    lista as removidas.
    """
    marks = {dest: (kind, old) for kind, dest, old, _ in (changes or [])}
    title = "TABELA DE ROTEAMENTO" + (" (atualizada)" if changes else "")
    lines = ["", _paint(title, BOLD, color),
             f"  {'Destino':<16} {'Custo total':>11}   {'Próximo salto':<16}",
             f"  {'-' * 16} {'-' * 11}   {'-' * 16}"]

    for dest in sorted(routes, key=ip_key):
        r = routes[dest]
        row = f"  {dest:<16} {r.cost:>11}   {r.next_hop:<16}"
        if r.options > 1:
            row += f" (empate entre {r.options})"
        kind, old = marks.get(dest, (None, None))
        if kind == "NOVA":
            row = _paint(row + "  [NOVA]", GREEN, color)
        elif kind == "ALTERADA":
            row = _paint(row + f"  [ALTERADA: antes custo {old.cost} via {old.next_hop}]", YELLOW, color)
        lines.append(row)

    for kind, dest, old, _ in changes or []:
        if kind == "REMOVIDA":
            row = f"  {dest:<16} {'-':>11}   {'-':<16}  [REMOVIDA: era custo {old.cost} via {old.next_hop}]"
            lines.append(_paint(row, RED, color))

    if not routes and not any(k == "REMOVIDA" for k, *_ in changes or []):
        lines.append("  (sem rotas)")
    return "\n".join(lines) + "\n"


def format_lsdb(router):
    now = router.clock()
    lsdb = router.lsdb
    lines = ["", f"LSDB ({len(lsdb.entries)} origens)",
             f"  {'Origem':<16} {'SEQ':>6}  {'Recebido em':<12} {'Expira em':>9}  Enlaces (vizinho;custo)",
             f"  {'-' * 16} {'-' * 6}  {'-' * 12} {'-' * 9}  {'-' * 30}"]
    for origin in sorted(lsdb.entries, key=ip_key):
        e = lsdb.entries[origin]
        received = datetime.fromtimestamp(e.received_wall).strftime("%H:%M:%S")
        if origin == router.my_ip:
            expires = "local"
        else:
            expires = f"{max(0.0, settings.LSA_MAX_AGE - (now - e.received_at)):.0f} s"
        links = " ".join(f"{n};{c}" for n, c in sorted(e.links.items(), key=lambda x: ip_key(x[0])))
        lines.append(f"  {origin:<16} {e.seq:>6}  {received:<12} {expires:>9}  {links or '(nenhum)'}")

    gone = sorted((o for o in lsdb.max_seq if o not in lsdb.entries), key=ip_key)
    if gone:
        lines.append("  Origens expiradas (maior SEQ aceito, mantido para descartar LSAs antigos): "
                     + ", ".join(f"{o} SEQ={lsdb.max_seq[o]}" for o in gone))
    return "\n".join(lines) + "\n"


def format_neighbors(router):
    now = router.clock()
    lines = ["", f"VIZINHOS (IP local {router.my_ip})",
             f"  {'Vizinho':<16} {'Custo':>6}  {'Enlace':<11} {'Estado':<8} {'Último HELLO':>12}",
             f"  {'-' * 16} {'-' * 6}  {'-' * 11} {'-' * 8} {'-' * 12}"]
    for ip in sorted(router.neighbors, key=ip_key):
        n = router.neighbors[ip]
        link = "ativado" if n.enabled else "DESATIVADO"
        state = "ATIVO" if n.active else "inativo"
        last = "nunca" if n.last_hello is None else f"há {now - n.last_hello:.0f} s"
        lines.append(f"  {ip:<16} {n.cost:>6}  {link:<11} {state:<8} {last:>12}")
    if not router.neighbors:
        lines.append("  (nenhum vizinho configurado)")
    return "\n".join(lines) + "\n"
