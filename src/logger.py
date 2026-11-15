"""Registro de eventos: `HH:MM:SS.mmm | TIPO | campo | campo ...`

Tudo vai para o arquivo de log. Na tela, o nível pode ser:
  tudo       – todos os eventos
  sem-hello  – esconde HELLO_ENVIADO/HELLO_RECEBIDO (são muitos)
  nada       – nada (use `tail -f router.log` em outro terminal)
"""

import threading
from datetime import datetime

SCREEN_LEVELS = ("tudo", "sem-hello", "nada")
HELLO_EVENTS = {"HELLO_ENVIADO", "HELLO_RECEBIDO"}


class Logger:
    def __init__(self, path=None, screen="tudo", out=print):
        self.screen = screen
        self.out = out
        self.lines = []          # cópia em memória (útil nos testes)
        self.keep_in_memory = path is None
        self._file = open(path, "a", encoding="utf-8") if path else None
        self._lock = threading.Lock()

    def log(self, event, *fields):
        parts = [event] + [str(f) for f in fields if f is not None and f != ""]
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"{stamp} | " + " | ".join(parts)
        with self._lock:
            if self._file:
                self._file.write(line + "\n")
                self._file.flush()
            if self.keep_in_memory:
                self.lines.append(line)
            if self._show(event):
                self.out(line)

    def _show(self, event):
        if self.screen == "nada":
            return False
        if self.screen == "sem-hello" and event in HELLO_EVENTS:
            return False
        return True

    def close(self):
        if self._file:
            self._file.close()
