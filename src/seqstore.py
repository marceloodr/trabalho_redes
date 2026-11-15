"""Persistência do número de sequência do LSA local (seq.txt).

A especificação exige gravar ANTES de enviar cada LSA novo. Assim, se o
processo cair logo depois do envio, ao reiniciar ele continua de (gravado + 1)
e os vizinhos não descartam o novo LSA como "antigo".
"""

import os


def load(path):
    """Último número de sequência usado (0 se o arquivo não existe ou é inválido)."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
    except FileNotFoundError:
        return 0
    return int(text) if text.isascii() and text.isdigit() else 0


def save(path, seq):
    """Grava `seq` de forma durável: escreve num temporário, fsync e troca o arquivo."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(str(seq))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
