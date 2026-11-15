"""Constantes do protocolo e políticas configuráveis.

Tudo que é "número mágico" da especificação fica aqui, num só lugar.
"""

# ---------------------------------------------------------------------------
# Protocolo (fixo pela especificação)
# ---------------------------------------------------------------------------
PORT = 6000                 # porta UDP usada por todos os grupos
MAX_PACKET = 1200           # tamanho máximo de um datagrama da aplicação (bytes)

HELLO_INTERVAL = 5          # envia HELLO a cada 5 s
LSA_INTERVAL = 10           # renova o LSA local a cada 10 s
NEIGHBOR_TIMEOUT = 15       # vizinho inativo após 15 s sem HELLO válido
LSA_MAX_AGE = 30            # LSA remoto expira 30 s após a última versão nova aceita

DEFAULT_TTL = 16            # TTL padrão das mensagens DATA

# Limites dos campos (pág. 7 da definição; TTL 0-255 também está no texto principal)
MIN_COST, MAX_COST = 1, 65535
MIN_SEQ, MAX_SEQ = 1, 2147483647
MIN_TTL, MAX_TTL = 0, 255

# Arquivos (relativos à pasta do roteador, ver --dir)
CONFIG_FILE = "roteadores.txt"
SEQ_FILE = "seq.txt"
LOG_FILE = "router.log"

# Intervalo do "relógio" interno que dispara os temporizadores
TICK_INTERVAL = 0.5

# ---------------------------------------------------------------------------
# Políticas para os pontos em que a definição é ambígua (ver PLANO.md §0).
# Seguem o TEXTO PRINCIPAL da definição; trocar aqui se o professor decidir
# pela versão da pág. 7.
# ---------------------------------------------------------------------------

# De quem aceitar LSA: "ativo" (texto principal) ou "configurado" (pág. 7)
ACEITAR_LSA_DE = "ativo"

# Desempate entre caminhos de mesmo custo: "aleatorio" (texto) ou "menor_ip" (pág. 7)
DESEMPATE = "aleatorio"

# Ao receber o próprio LSA com SEQ maior que o atual, pular a sequência?
# Texto principal: não (sempre descarta). Pág. 7: sim.
SALTAR_SEQ_PROPRIA = False

# Exigir que o IP_ORIGEM do HELLO seja o IP de onde veio o datagrama
EXIGIR_ORIGEM_HELLO_IGUAL_REMETENTE = True
