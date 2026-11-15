"""Socket UDP na porta 6000: envio e thread de recepção."""

import socket
import threading

import settings


class UdpTransport:
    def __init__(self, bind_ip, on_datagram, on_error=print, port=settings.PORT):
        self.port = port
        self.on_datagram = on_datagram    # função (bytes, ip_remetente)
        self.on_error = on_error
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # No Windows, um ICMP "porta inalcançável" faz o próximo recvfrom falhar
        # com WSAECONNRESET; isto desliga esse comportamento.
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            self.sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        # bind no IP do roteador: os datagramas saem com esse IP de origem
        self.sock.bind((bind_ip, port))
        self._running = False

    def send(self, ip, data):
        self.sock.sendto(data, (ip, self.port))

    def start(self):
        self._running = True
        threading.Thread(target=self._receive_loop, name="recepcao", daemon=True).start()

    def _receive_loop(self):
        while self._running:
            try:
                # buffer maior que 1200 para conseguir detectar (e descartar) pacotes grandes
                data, (ip, _port) = self.sock.recvfrom(65535)
            except OSError as e:
                if not self._running:
                    break
                self.on_error(f"erro de recepção: {e}")
                continue
            try:
                self.on_datagram(data, ip)
            except Exception as e:  # um pacote estranho nunca deve derrubar a recepção
                self.on_error(f"erro ao tratar datagrama de {ip}: {e!r}")

    def close(self):
        self._running = False
        self.sock.close()
