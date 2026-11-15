import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import protocol  # noqa: E402
from protocol import ParseError  # noqa: E402


def parse(text):
    return protocol.parse(protocol.decode(text.encode("utf-8")))


class TestValid(unittest.TestCase):
    def test_hello(self):
        h = parse("@192.168.1.1*192.168.1.2*192.168.1.3")
        self.assertEqual(h.origin, "192.168.1.1")
        self.assertEqual(h.neighbors, ("192.168.1.2", "192.168.1.3"))

    def test_hello_without_neighbors(self):
        self.assertEqual(parse("@192.168.1.1").neighbors, ())

    def test_lsa(self):
        lsa = parse("#192.168.1.1;25*192.168.1.2;10*192.168.1.3;5")
        self.assertEqual((lsa.origin, lsa.seq), ("192.168.1.1", 25))
        self.assertEqual(lsa.links, {"192.168.1.2": 10, "192.168.1.3": 5})

    def test_lsa_without_links(self):
        self.assertEqual(parse("#192.168.1.1;5").links, {})

    def test_data(self):
        d = parse("!192.168.1.1;192.168.1.7;1001;16;Olá pessoal!")
        self.assertEqual((d.origin, d.dest, d.msg_id, d.ttl, d.text),
                         ("192.168.1.1", "192.168.1.7", 1001, 16, "Olá pessoal!"))

    def test_data_text_with_semicolon(self):
        self.assertEqual(parse("!1.1.1.1;2.2.2.2;1;0;a;b;c").text, "a;b;c")

    def test_limits_accepted(self):
        parse("#1.1.1.1;2147483647*2.2.2.2;65535*3.3.3.3;1")
        parse("!1.1.1.1;2.2.2.2;1;255;x")

    def test_format_roundtrip(self):
        text = protocol.format_lsa("10.0.0.1", 3, {"10.0.0.10": 4, "10.0.0.2": 7})
        self.assertEqual(text, "#10.0.0.1;3*10.0.0.2;7*10.0.0.10;4")  # ordem numérica
        self.assertEqual(parse(text).links, {"10.0.0.2": 7, "10.0.0.10": 4})
        self.assertEqual(protocol.format_hello("1.1.1.1", ["2.2.2.2"]), "@1.1.1.1*2.2.2.2")
        self.assertEqual(protocol.format_data("1.1.1.1", "2.2.2.2", 7, 16, "oi"), "!1.1.1.1;2.2.2.2;7;16;oi")


class TestInvalid(unittest.TestCase):
    CASES = [
        "",                                      # vazio
        "@192.168.1.1\n",                        # quebra de linha no final
        "?192.168.1.1",                          # tipo desconhecido
        "@192.168.1.300",                        # IP inválido
        "@192.168.1.1*",                         # vizinho vazio
        "@192.168.01.1",                         # zero à esquerda
        "@ 192.168.1.1",                         # espaço
        "#192.168.1.1",                          # sem SEQ
        "#192.168.1.1;0",                        # SEQ 0
        "#192.168.1.1;2147483648",               # SEQ acima do limite
        "#192.168.1.1;+5",                       # sinal
        "#192.168.1.1;5*192.168.1.2;0",          # custo 0
        "#192.168.1.1;5*192.168.1.2;-3",         # custo negativo
        "#192.168.1.1;5*192.168.1.2;65536",      # custo acima do limite
        "#192.168.1.1;5*192.168.1.2;abc",        # custo texto
        "#192.168.1.1;5*192.168.1.2",            # sem custo
        "#192.168.1.1;5*192.168.1.2;3*192.168.1.2;4",  # vizinho repetido
        "#192.168.1.1;5*192.168.1.1;3",          # enlace para si
        "!1.1.1.1;2.2.2.2;1;256;x",              # TTL > 255
        "!1.1.1.1;2.2.2.2;1;-1;x",               # TTL negativo
        "!1.1.1.1;2.2.2.2;abc;5;x",              # ID inválido
        "!1.1.1.1;2.2.2.2;1;5",                  # sem mensagem
    ]

    def test_invalid(self):
        for text in self.CASES:
            with self.subTest(text=text), self.assertRaises(ParseError):
                parse(text)

    def test_too_big(self):
        with self.assertRaises(ParseError):
            protocol.decode(("!1.1.1.1;2.2.2.2;1;5;" + "x" * 1200).encode())
        with self.assertRaises(ValueError):
            protocol.encode("x" * 1201)
        protocol.encode("x" * 1200)

    def test_not_utf8(self):
        with self.assertRaises(ParseError):
            protocol.decode(b"@1.1.1.1\xff")


if __name__ == "__main__":
    unittest.main()
