#!/bin/bash
# Instala o dissector Lua e o perfil "TF-Redes" do Wireshark para o usuário atual (macOS/Linux).
# Depois: Wireshark > Edit > Configuration Profiles > TF-Redes (ou clique em "Profile" no canto inferior direito).
set -e
cd "$(dirname "$0")"
mkdir -p ~/.local/lib/wireshark/plugins ~/.config/wireshark/profiles/TF-Redes
cp linkstate.lua ~/.local/lib/wireshark/plugins/
cp perfil-TF-Redes/* ~/.config/wireshark/profiles/TF-Redes/
echo "Dissector: ~/.local/lib/wireshark/plugins/linkstate.lua"
echo "Perfil:    ~/.config/wireshark/profiles/TF-Redes"
