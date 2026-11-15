"""Leitura e gravação do roteadores.txt (uma linha `IP;CUSTO` por vizinho)."""

import os

import settings
from protocol import ip_key, is_ipv4


def load_neighbors(path, my_ip=None, warn=print):
    """Lê o arquivo e devolve {ip_vizinho: custo}. Linhas inválidas são ignoradas com aviso."""
    neighbors = {}
    if not os.path.exists(path):
        warn(f"AVISO: {path} não encontrado; iniciando sem vizinhos.")
        return neighbors

    with open(path, encoding="utf-8-sig") as f:  # utf-8-sig ignora BOM do Bloco de Notas
        for number, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            fields = [x.strip() for x in line.split(";")]
            if len(fields) != 2 or not is_ipv4(fields[0]) or not fields[1].isdigit():
                warn(f"AVISO: {path}:{number}: linha inválida ignorada: {line!r}")
                continue
            ip, cost = fields[0], int(fields[1])
            if not settings.MIN_COST <= cost <= settings.MAX_COST:
                warn(f"AVISO: {path}:{number}: custo fora de {settings.MIN_COST}-{settings.MAX_COST}: {cost}")
                continue
            if ip == my_ip:
                warn(f"AVISO: {path}:{number}: o próprio IP não pode ser vizinho; ignorado")
                continue
            neighbors[ip] = cost
    return neighbors


def save_neighbors(path, neighbors):
    """Regrava o arquivo inteiro (grava num temporário e troca, para não corromper)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for ip in sorted(neighbors, key=ip_key):
            f.write(f"{ip};{neighbors[ip]}\n")
    os.replace(tmp, path)
