# Roteador Link State (inspirado no OSPF) – Trabalho Final de Redes

Python 3.8+ e só a biblioteca padrão. Comunicação por UDP na porta 6000.

## Como executar

Cada roteador roda numa pasta com o seu `roteadores.txt` (uma linha `IP;CUSTO` por vizinho).
O `seq.txt` e o `router.log` são criados na mesma pasta.

```bash
python3 src/main.py --ip 192.168.1.1 --dir topologia/r1
```

| Opção | Significado |
|---|---|
| `--ip` | IPv4 deste roteador. Sem ele, o programa detecta o IP da interface que leva ao 1º vizinho. |
| `--dir` | pasta com `roteadores.txt`, `seq.txt` e `router.log` (padrão: pasta atual) |
| `--log-tela` | `tudo`, `sem-hello` (padrão) ou `nada`. O arquivo de log sempre recebe tudo. |

Dica para a demonstração: use um terminal para os comandos e outro para acompanhar o log completo:

```bash
tail -f topologia/r1/router.log
```

No Windows, a mesma coisa no PowerShell: `Get-Content topologia\r1\router.log -Wait`.

## Comandos

| Comando | O que faz |
|---|---|
| `lsdb` | mostra a LSDB (origem, SEQ, hora de recebimento, tempo até expirar, enlaces) |
| `rotas` | mostra a tabela de roteamento (destino, custo total, próximo salto) |
| `vizinhos` | mostra os vizinhos configurados, o custo, se o enlace está ativado e se a vizinhança está ativa |
| `down <ip>` | desativa o enlace lógico: para de enviar HELLO e descarta HELLO/LSA desse vizinho |
| `up <ip>` | reativa o enlace; a vizinhança volta só depois de um HELLO válido |
| `custo <ip> <n>` | altera o custo (1–65535), gera LSA na hora e grava o `roteadores.txt` |
| `add <ip> <n>` | adiciona um vizinho e grava o `roteadores.txt` |
| `del <ip>` | remove um vizinho e grava o `roteadores.txt` |
| `send <ip> [ttl=N] <texto>` | envia DATA (TTL de 0 a 255, padrão 16). Ex.: `send 192.168.1.5 ttl=1 oi` |
| `replay <vizinho> <origem> dup` | reenvia ao vizinho o LSA armazenado de `<origem>` com o mesmo SEQ (duplicado) |
| `replay <vizinho> <origem> old [seq]` | igual, mas com SEQ menor (padrão: SEQ − 1), ou seja, um LSA antigo |
| `log tudo\|sem-hello\|nada` | muda o que aparece do log nesta tela |
| `help`, `sair` | ajuda e encerrar |

Os comandos também aceitam nomes em português: `tabela`, `desativar`, `ativar`, `adicionar`, `remover`, `enviar`, `reenviar` e `ajuda`.

## Testes

```bash
python3 -m unittest discover -s tests -v
```

- `tests/test_protocol.py` – validação das mensagens (formatos, limites, 1200 bytes, quebra de linha).
- `tests/test_dijkstra.py` – grafo bidirecional, custo assimétrico, empate, próximo salto ativo.
- `tests/test_scenarios.py` – cenários A–H do relatório numa rede simulada (`tests/simnet.py`).
  Os roteadores são os de verdade (classe `Router`), mas a rede é simulada e o relógio é falso: 30 s passam em milissegundos.

### Vários roteadores numa máquina só

Cada roteador precisa de um IP próprio, porque todos usam a porta 6000. No macOS, crie IPs de loopback (pede senha de administrador):

```bash
for i in 2 3 4 5 6; do sudo ifconfig lo0 alias 127.0.0.$i up; done
```

No Linux, todo o bloco `127.0.0.0/8` já funciona sem configurar nada. Depois, crie uma pasta por roteador com um `roteadores.txt` que use esses IPs, e rode:

```bash
python3 src/main.py --ip 127.0.0.2 --dir /tmp/r2
```

## Organização do código

```
src/
  main.py       linha de comando, argumentos, threads (temporizadores e CLI)
  router.py     núcleo: HELLO, vizinhança, LSA local, flooding, DATA, comandos
  lsdb.py       LSDB (versão mais recente por origem, maior SEQ, expiração)
  dijkstra.py   grafo bidirecional + Dijkstra próprio + diferença entre tabelas
  protocol.py   formato das mensagens: validação e montagem
  transport.py  socket UDP (porta 6000) e thread de recepção
  views.py      tabelas exibidas no terminal
  config.py     leitura/gravação do roteadores.txt
  seqstore.py   seq.txt (gravado antes de cada LSA enviado)
  logger.py     log na tela e no arquivo
  settings.py   temporizadores, limites e políticas (pontos ambíguos da definição)
topologia/r1..r6  roteadores.txt da topologia de teste (192.168.1.1–6; ajuste aos IPs do laboratório)
```

### Threads

- **recepção** (`transport.py`): `recvfrom` → `Router.handle_datagram`
- **temporizadores** (`main.py`): a cada 0,5 s chama `Router.tick` (HELLO 5 s, timeout 15 s, expiração 30 s, LSA 10 s)
- **principal**: lê os comandos

Todo o estado do roteador fica protegido por um único `RLock` (`Router.lock`).

### Políticas configuráveis (`src/settings.py`)

| Constante | Padrão (texto da definição) | Alternativa (pág. 7) |
|---|---|---|
| `ACEITAR_LSA_DE` | `"ativo"` | `"configurado"` |
| `DESEMPATE` | `"aleatorio"` | `"menor_ip"` |
| `SALTAR_SEQ_PROPRIA` | `False` | `True` |

Com `"aleatorio"`, quando uma rota empatada é recalculada e o próximo salto anterior continua entre os melhores, ele é mantido. Assim a rota não aparece como "alterada" sem motivo.
