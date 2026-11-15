"""Formato das mensagens na rede: validação (parse) e montagem (format).

    HELLO:  @IP_ORIGEM*VIZINHO1*VIZINHO2*...
    LSA:    #IP_ORIGEM;SEQUENCIA*VIZINHO1;CUSTO*VIZINHO2;CUSTO
    DATA:   !IP_ORIGEM;IP_DESTINO;ID;TTL;MENSAGEM

Qualquer problema de formato levanta ParseError com o motivo, que o roteador
registra no log antes de descartar o datagrama.
"""

import ipaddress
from dataclasses import dataclass, field

import settings


class ParseError(Exception):
    """Mensagem malformada (o texto da exceção é o motivo do descarte)."""


@dataclass(frozen=True)
class Hello:
    origin: str
    neighbors: tuple  # vizinhos configurados do emissor


@dataclass(frozen=True)
class Lsa:
    origin: str
    seq: int
    links: dict = field(hash=False)  # {ip_vizinho: custo}


@dataclass(frozen=True)
class Data:
    origin: str
    dest: str
    msg_id: int
    ttl: int
    text: str


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

def is_ipv4(text):
    """True se `text` é um IPv4 em notação decimal (ex.: 192.168.1.1)."""
    try:
        ipaddress.IPv4Address(text)
        return True
    except ValueError:
        return False


def ip_key(ip):
    """Chave para ordenar IPs numericamente (192.168.1.9 < 192.168.1.10)."""
    return int(ipaddress.IPv4Address(ip))


def _ip(text, what):
    if not is_ipv4(text):
        raise ParseError(f"{what} não é um IPv4 válido: {text!r}")
    return text


def _int(text, what, low, high):
    # isdigit() sozinho aceita '²' e int() aceita '+5', ' 5', '1_0'; exigimos só 0-9.
    if not (text.isascii() and text.isdigit()):
        raise ParseError(f"{what} não é um inteiro: {text!r}")
    value = int(text)
    if not low <= value <= high:
        raise ParseError(f"{what} fora do intervalo {low}-{high}: {value}")
    return value


# ---------------------------------------------------------------------------
# Bytes <-> texto
# ---------------------------------------------------------------------------

def decode(data):
    """Valida o datagrama bruto (tamanho, UTF-8, quebra de linha) e devolve o texto."""
    if len(data) > settings.MAX_PACKET:
        raise ParseError(f"datagrama com {len(data)} bytes (máximo {settings.MAX_PACKET})")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ParseError("conteúdo não é UTF-8 válido") from None
    if not text:
        raise ParseError("datagrama vazio")
    if text.endswith("\n") or text.endswith("\r"):
        raise ParseError("quebra de linha ao final da mensagem")
    return text


def encode(text):
    """Texto -> bytes, garantindo o limite de 1200 bytes."""
    data = text.encode("utf-8")
    if len(data) > settings.MAX_PACKET:
        raise ValueError(f"mensagem com {len(data)} bytes excede {settings.MAX_PACKET}")
    return data


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse(text):
    """Converte o texto em Hello, Lsa ou Data. Levanta ParseError se inválido."""
    kind = text[0]
    if kind == "@":
        return parse_hello(text)
    if kind == "#":
        return parse_lsa(text)
    if kind == "!":
        return parse_data(text)
    raise ParseError(f"tipo de mensagem desconhecido: {kind!r}")


def parse_hello(text):
    parts = text[1:].split("*")
    origin = _ip(parts[0], "IP_ORIGEM")
    neighbors = tuple(_ip(p, "VIZINHO") for p in parts[1:])
    return Hello(origin, neighbors)


def parse_lsa(text):
    parts = text[1:].split("*")
    header = parts[0].split(";")
    if len(header) != 2:
        raise ParseError("cabeçalho do LSA deve ser IP_ORIGEM;SEQUENCIA")
    origin = _ip(header[0], "IP_ORIGEM")
    seq = _int(header[1], "SEQUENCIA", settings.MIN_SEQ, settings.MAX_SEQ)

    links = {}
    for part in parts[1:]:
        fields = part.split(";")
        if len(fields) != 2:
            raise ParseError(f"enlace deve ser VIZINHO;CUSTO: {part!r}")
        neighbor = _ip(fields[0], "VIZINHO")
        cost = _int(fields[1], "CUSTO", settings.MIN_COST, settings.MAX_COST)
        if neighbor == origin:
            raise ParseError("LSA anuncia enlace para a própria origem")
        if neighbor in links:
            raise ParseError(f"vizinho repetido no LSA: {neighbor}")
        links[neighbor] = cost
    return Lsa(origin, seq, links)


def parse_data(text):
    # maxsplit=4: a MENSAGEM pode conter ';'
    fields = text[1:].split(";", 4)
    if len(fields) != 5:
        raise ParseError("DATA deve ser IP_ORIGEM;IP_DESTINO;ID;TTL;MENSAGEM")
    origin = _ip(fields[0], "IP_ORIGEM")
    dest = _ip(fields[1], "IP_DESTINO")
    msg_id = _int(fields[2], "ID", 0, 2**63 - 1)
    ttl = _int(fields[3], "TTL", settings.MIN_TTL, settings.MAX_TTL)
    return Data(origin, dest, msg_id, ttl, fields[4])


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------

def format_hello(origin, neighbors):
    return "@" + "*".join([origin, *neighbors])


def format_lsa(origin, seq, links):
    text = f"#{origin};{seq}"
    for neighbor in sorted(links, key=ip_key):
        text += f"*{neighbor};{links[neighbor]}"
    return text


def format_data(origin, dest, msg_id, ttl, text):
    return f"!{origin};{dest};{msg_id};{ttl};{text}"
