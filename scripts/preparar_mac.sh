#!/bin/bash
# Prepara um Mac para rodar os 6 roteadores numa máquina só e capturar com o Wireshark.
# Precisa de administrador:   sudo bash scripts/preparar_mac.sh
#
#  1. cria os IPs de loopback 127.0.0.2 a 127.0.0.6 (cada roteador precisa de um IP,
#     porque todos usam a porta 6000). Somem ao reiniciar o Mac.
#  2. instala o ChmodBPF do Wireshark (permite capturar sem ser root).
set -e

if [ "$(id -u)" -ne 0 ]; then
  echo "Rode com sudo: sudo bash $0" >&2
  exit 1
fi

for i in 2 3 4 5 6; do
  ifconfig lo0 alias 127.0.0.$i up
done
echo "IPs de loopback:"; ifconfig lo0 | grep 'inet 127'

USER_HOME=$(eval echo "~${SUDO_USER:-$USER}")
PKG="$USER_HOME/Downloads/Install ChmodBPF.pkg"
DMG=$(ls "$USER_HOME"/Downloads/Wireshark*.dmg 2>/dev/null | head -1 || true)

if [ -f "$PKG" ]; then
  installer -pkg "$PKG" -target /
elif [ -n "$DMG" ]; then
  MP=$(hdiutil attach -nobrowse -readonly "$DMG" | awk -F'\t' '/\/Volumes\//{print $NF}' | tail -1)
  installer -pkg "$MP/Install ChmodBPF.pkg" -target /
  hdiutil detach "$MP" >/dev/null
else
  echo "Não achei o 'Install ChmodBPF.pkg' nem o .dmg do Wireshark em ~/Downloads." >&2
  exit 1
fi

# O ChmodBPF dá acesso ao grupo access_bpf; garante que o usuário está nele.
dseditgroup -o edit -a "${SUDO_USER:-$USER}" -t user access_bpf 2>/dev/null || true
# Reaplica as permissões agora (o daemon faz isso a cada boot).
chgrp access_bpf /dev/bpf* && chmod g+rw /dev/bpf*
ls -l /dev/bpf0
echo "Pronto. Se a captura ainda falhar por permissão, faça logout/login."
