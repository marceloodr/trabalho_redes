# Plano – Trabalho Final de Redes (Link State inspirado no OSPF)

> Entrega: **18/11/2026** (plano revisado em 13/11 → **5 dias**). Entregáveis: código-fonte, relatório em PDF, capturas `.pcap/.pcapng`.
> Demonstração em ≥ 4 computadores, interoperando com outros grupos. Um integrante sorteado explica tudo → **todos precisam entender o código**.
> Itens marcados com **(novo)** vieram da versão da definição de 13/11.

---

## 0. O que mudou na definição (versão de 13/11)

### Mudanças no texto principal (valem como regra)
| # | Antes | Agora | Impacto no plano |
|---|---|---|---|
| 1 | Arquivo de sequência sem nome definido | **`seq.txt`**; ao reiniciar, continua do valor gravado **+ 1** | renomear arquivo (§4.3) |
| 2 | Nada sobre receber o próprio LSA | LSA com **o próprio IP de origem → descartar**, sem processar nem encaminhar | removida a ideia de "pular a sequência" (§4.4) |
| 3 | — | **Próximo salto sempre é um vizinho ativo** | checagem no Dijkstra e no envio de DATA (§4.5, §4.6) |
| 4 | Desativar enlace: só parar HELLO | Desativar enlace: parar de enviar HELLO **e descartar HELLOs e LSAs recebidos dele** | §4.2, §4.4, §4.7 |
| 5 | Adicionar vizinho | **Adicionar e remover** vizinho, **atualizando `roteadores.txt`**; ativo só quando o outro lado também configurar | §4.7 |
| 6 | Reenvio de LSA para teste não especificado | Comando para **reenviar a um vizinho o LSA armazenado de uma origem** (qualquer origem da LSDB), com a **sequência original (duplicado)** ou **sequência menor (antigo)** | novo comando `replay` (§4.7, cenário F) |
| 7 | TTL sempre 16 | TTL inicial **opcional, 0 a 255, padrão 16** | validação + comando `send` (§4.6) |
| 8 | Ambíguo se a origem decrementa o TTL | **Origem envia com o TTL inicial sem decrementar**; cada intermediário verifica e decrementa. Caminho com *k* intermediários exige TTL ≥ *k* | ambiguidade resolvida (§4.6, cenário H, §7) |

### ⚠️ Página 7 – "Decisões novas para você validar" (conflita com o texto)
A última página parece ser uma nota de rascunho para o professor (a seção "Falhas e alterações na topologia" também aparece **repetida 3 vezes** na pág. 3). Ela propõe regras que **contradizem** o corpo do documento:

| Assunto | Corpo do documento | Pág. 7 (rascunho) |
|---|---|---|
| Aceitação de LSA | só de **vizinho ativo** (págs. 2 e 4) | de **qualquer vizinho configurado** (evita perder a sincronização inicial) |
| Empate no Dijkstra | **aleatório** | **menor IP** de próximo salto |
| Próprio LSA com seq maior | **descartar** sem processar | **saltar** a própria sequência |
| Limites | só TTL 0–255 | custo **1–65535**, seq **≤ 2147483647**, TTL 0–255 |

**Ação:** perguntar ao professor **hoje** qual versão vale e avisar a turma. Enquanto isso:
- seguir o **corpo do documento**;
- deixar cada um desses pontos como **constante de configuração** no código (`ACEITAR_LSA_DE = "ativo" | "configurado"`, `DESEMPATE = "aleatorio" | "menor_ip"`, `SALTAR_SEQ_PROPRIA = False`) para trocar em 1 linha;
- adotar os **limites** da pág. 7 (não conflitam com nada e ajudam a interoperar).

---

## 1. Resumo do que precisa existir

| Bloco | O que fazer | Requisito-chave |
|---|---|---|
| Configuração | Ler `roteadores.txt` (`IP;CUSTO` por linha) | custos inteiros > 0 (limite proposto 1–65535) |
| HELLO | Enviar a cada **5 s** a todos os vizinhos configurados e habilitados | `@ORIGEM*V1*V2...` |
| Vizinhança | Ativa só se recebeu HELLO **e** ambos se listam (bidirecional) | inativa após **15 s** sem HELLO |
| LSA local | Gerar a cada **10 s** + sempre que enlaces/custos mudarem | `#ORIGEM;SEQ*V1;C1*V2;C2` |
| Sequência | Começa em 1, +1 a cada LSA (inclusive periódico), **gravada em `seq.txt` antes de enviar** **(novo)** | reinício continua do gravado + 1 |
| LSDB | Por origem: IP, seq, enlaces, instante de recebimento | exibida separada da tabela |
| Flooding | Aceitar só de vizinho ativo e só se seq > maior já aceito; repassar a todos os ativos exceto quem enviou | duplicados/antigos: descartar, sem flood, sem renovar validade |
| Próprio LSA **(novo)** | LSA recebido com origem = meu IP → descartar | sem processar nem encaminhar |
| Sincronização | Ao formar vizinhança, enviar ao novo vizinho **todos** os LSAs válidos da LSDB | sem ACK/retransmissão |
| Expiração | LSA remoto vale **30 s** desde a última versão nova aceita | manter maior seq por origem mesmo após expirar |
| Dijkstra | Implementação própria; roda só quando a topologia muda | aresta só se as duas pontas a anunciam; **próximo salto sempre vizinho ativo (novo)**; empate aleatório; sem rota para si |
| Tabela | Destino / Custo total / Próximo salto | destacar rotas novas, removidas e alteradas |
| DATA | Usuário envia texto a qualquer IP; **TTL opcional 0–255, padrão 16 (novo)** | `!ORIGEM;DESTINO;ID;TTL;MSG`; **origem não decrementa (novo)** |
| Comandos | Ver LSDB/rotas, ativar/desativar enlace, custo, **adicionar/remover vizinho**, enviar DATA, **reenviar LSA duplicado/antigo (novo)** | sem reiniciar o processo |
| Log | Tipo de evento + origem + descrição, na tela e em arquivo | ex.: `LSA_ACEITO \| 192.168.1.3 \| SEQ=7` |
| Protocolo | UDP **porta 6000**, UTF-8, IPv4, ≤ **1200 bytes**, sem `\n` no fim | malformado/grande: descartar e registrar |

---

## 2. Decisões técnicas recomendadas

- **Linguagem: Python 3 (só biblioteca padrão)** – `socket`, `threading`, `time`, `random`, `ipaddress`, `heapq` (fila de prioridade é estrutura de dados, permitida; o Dijkstra é nosso).
- **Concorrência:** threads + **um único `threading.Lock`** protegendo todo o estado.
  - Thread receptora: `recvfrom` em loop → despacha pelo 1º caractere (`@`, `#`, `!`).
  - Thread de temporizadores: tick de ~1 s → HELLO (5 s), LSA (10 s), vizinhos mortos (15 s), expiração (30 s).
  - Thread principal: CLI.
- **IP próprio:** não está no `roteadores.txt` → argumento `--ip 192.168.1.1` (detecção automática como fallback).
- **Bind no IP próprio** (`sock.bind((meu_ip, 6000))`) para o IP de origem dos datagramas ser o correto e para permitir testes locais com vários IPs de loopback.
- **Quem enviou o datagrama** = `addr[0]` do `recvfrom` (não o `IP_ORIGEM` do LSA).
- **Cada roteador roda na sua própria pasta**, já que `roteadores.txt` e `seq.txt` têm nome fixo.
- **Log:** tela + arquivo `router.log`; um segundo terminal com `tail -f router.log` como "tela de log".
- **Constantes de política** (ver §0) num único bloco no topo do código.

---

## 3. Estrutura do código (sugerida)

```
src/
  router.py      # main: argumentos, inicialização, threads, CLI
  config.py      # ler/gravar roteadores.txt (add/del/custo)
  protocol.py    # parse + validação + formatação de HELLO/LSA/DATA
  state.py       # estruturas: vizinhos, LSDB, max_seq, tabela de rotas
  lsdb.py        # aceitar LSA, flooding, expiração, sincronização, replay
  dijkstra.py    # construção do grafo + Dijkstra + diff da tabela
  data.py        # envio/encaminhamento de DATA
  logger.py      # log padronizado (tela + arquivo)
  seqstore.py    # seq.txt
tests/           # testes unitários de parser e Dijkstra
topologia/r1..r6 # roteadores.txt (+ seq.txt e log gerados) de cada roteador
capturas/        # .pcapng
relatorio/       # fonte do relatório + PDF
```

### Estruturas de dados

```python
config_neighbors = { "192.168.1.2": 10, ... }        # do roteadores.txt (custo de MIM até ele)
neighbors = {
  "192.168.1.2": {
     "last_hello": 1731360000.0,   # instante do último HELLO válido
     "active": True,               # bidirecional confirmado
     "enabled": True,              # enlace lógico ligado/desligado por comando
  }
}
lsdb = {                                              # inclui o próprio LSA
  "192.168.1.3": {"seq": 7, "links": {"192.168.1.1": 5, "192.168.1.4": 7}, "received_at": t}
}
max_seq = { "192.168.1.3": 7 }   # nunca é apagado enquanto o processo roda
routes  = { "192.168.1.4": {"cost": 12, "next_hop": "192.168.1.2"} }
my_seq  = int(seq.txt) se existir, senão 0      # próximo LSA usa my_seq + 1
data_id = contador por execução
```

---

## 4. Como implementar cada parte

### 4.1 Validação (`protocol.py`) – fazer primeiro
Descartar e logar (`MSG_MALFORMADA` com motivo) quando:
- datagrama > 1200 bytes, não decodifica UTF-8, ou termina com `\n`/`\r`;
- 1º caractere não é `@`, `#` ou `!`;
- algum IP não é IPv4 válido (`ipaddress.IPv4Address`);
- **(novo)** custo fora de **1–65535**; seq fora de **1–2147483647**; TTL fora de **0–255**; ID não inteiro.

Casos de borda que **devem ser aceitos**: `@192.168.1.1` (HELLO sem vizinhos), `#192.168.1.1;5` (LSA sem enlaces), DATA com `;` no texto (`split(";", 4)`).
Ao **enviar**, garantir ≤ 1200 bytes (recusar texto de DATA grande).

### 4.2 HELLO e vizinhança
- A cada 5 s: para cada vizinho configurado **e habilitado**, enviar `@meu_ip*v1*v2...`.
- Ao receber HELLO de `addr[0]`:
  1. descartar se origem não é vizinho configurado, se `IP_ORIGEM != addr[0]` ou **se o enlace está desativado (novo)**;
  2. atualizar `last_hello` (`HELLO_RECEBIDO | origem`);
  3. se `meu_ip` está na lista do HELLO e estava inativo → **vizinhança estabelecida**:
     - `VIZINHO_ATIVO`;
     - **enviar um HELLO imediato a esse vizinho** (dica: faz o outro lado ativar na hora; sem isso a sincronização pode chegar antes de ele nos considerar ativo e ser descartada – é exatamente o problema citado na pág. 7);
     - gerar novo LSA local e fazer flood;
     - **enviar ao novo vizinho todos os LSAs válidos da LSDB**;
  4. se `meu_ip` **não** está na lista e estava ativo → derrubar vizinhança.
- Tick: vizinho ativo com `agora - last_hello > 15` → `VIZINHO_INATIVO`, novo LSA, flood, recalcular.

### 4.3 LSA local e `seq.txt`
```
gerar_lsa_local():
    my_seq += 1
    gravar my_seq em seq.txt (write + flush + os.fsync)        # ANTES de enviar
    links = {v: custo for v ativo}
    lsdb[meu_ip] = {seq, links, agora}; max_seq[meu_ip] = my_seq
    enviar "#meu_ip;seq*v;c*..." a todos os vizinhos ativos
    recalcular_se_topologia_mudou()
```
- Inicialização: se `seq.txt` existe, `my_seq = valor`; o 1º LSA sai com `valor + 1`. Senão começa em 1.
- Disparos: tick de 10 s, vizinho sobe/cai, custo alterado, enlace desativado, vizinho removido.
- O LSA local nunca expira.
- **(alterado)** Não há mais "salto de sequência": LSA com o próprio IP é sempre descartado (salvo decisão em contrário do professor – constante `SALTAR_SEQ_PROPRIA`). Consequência: **perder o `seq.txt` deixa o roteador "invisível"** até os outros reiniciarem (eles descartam seq 1, 2... como antigos). Não apagar o arquivo na demo.

### 4.4 Recebimento de LSA e flooding
```
on_lsa(pkt, remetente=addr[0]):
    se enlace com remetente está desativado     -> descarta (novo)
    se remetente não é vizinho ativo            -> descarta (motivo: vizinho inativo)   [constante ACEITAR_LSA_DE]
    se origem == meu_ip                         -> descarta, sem processar/encaminhar (novo)
    se seq <= max_seq.get(origem, 0)            -> descarta (DUPLICADO se ==, ANTIGO se <); não renova, não repassa
    aceita: lsdb[origem] = {seq, links, agora}; max_seq[origem] = seq        (LSA_ACEITO | origem | SEQ=n)
    repassa o datagrama original a todos os vizinhos ativos exceto o remetente  (LSA_ENCAMINHADO)
    recalcular_se_topologia_mudou()
```
- Expiração (tick): LSA remoto com `agora - received_at > 30` → remove (`LSA_EXPIRADO`), **mantém `max_seq`**, recalcula.

### 4.5 Dijkstra (`dijkstra.py`)
1. **Assinatura da topologia** = conjunto `(origem, vizinho, custo)` dos LSAs válidos. Só roda se mudou → renovação periódica não dispara Dijkstra.
2. **Grafo dirigido:** aresta `A→B` com o custo do LSA de A **somente se** o LSA de B também lista A.
3. **Dijkstra próprio** com `heapq`, a partir de `meu_ip`, guardando o conjunto de **primeiros saltos** de cada nó:
   - `nd < dist[v]` → `dist[v] = nd`, `first[v] = first(u)`;
   - `nd == dist[v]` → `first[v] |= first(u)`;
   - escolha: `random.choice(sorted(first[v]))` (ou `min` se `DESEMPATE = "menor_ip"`).
4. **(novo)** O próximo salto tem de ser **vizinho ativo**: as arestas que saem de mim vêm do meu LSA (que só lista ativos), então isso já vale; mesmo assim, filtrar `first[v]` pelos ativos e revalidar no envio de DATA.
5. Sem rota para si. Inalcançáveis ficam fora da tabela.
6. **Diff** com a tabela anterior → `[NOVA]`, `[REMOVIDA]`, `[ALTERADA] custo 18→16 / próximo salto X→Y`; logar `DIJKSTRA_EXECUTADO` e `ROTA_*`.
7. Primeiro cálculo logo após o primeiro LSA local.

### 4.6 DATA **(regras de TTL definidas)**
- Comando `send <ip_destino> <texto> [ttl]` – TTL **0–255, padrão 16**. ID = contador da execução.
- **Na origem:** consulta a rota; sem rota → `DATA_DESCARTADA (sem rota)`; senão envia ao próximo salto **com o TTL inicial, sem decrementar** (`DATA_ENVIADA`).
- **Ao receber:**
  ```
  se destino == meu_ip  -> exibe "Mensagem de X (ID n): texto"      (DATA_RECEBIDO)
  senão sem rota        -> descarta (DATA_DESCARTADA | motivo: sem rota)
  senão TTL == 0        -> descarta (DATA_DESCARTADA | motivo: TTL esgotado)
  senão TTL -= 1 e envia ao next_hop                                 (DATA_ENCAMINHADA)
  ```
- Regra prática: **caminho com *k* roteadores intermediários exige TTL ≥ *k***. Ex.: R1→R2→R4→R5 tem 2 intermediários → TTL 2 chega, TTL 1 morre em R4, TTL 0 morre em R2.

### 4.7 Comandos (CLI) – nomes livres, funções obrigatórias
| Comando | Efeito |
|---|---|
| `lsdb` | origem, seq, enlaces, idade/validade restante |
| `rotas` | Destino / Custo / Próximo salto |
| `vizinhos` | configurados, custo, ativo?, habilitado?, tempo desde último HELLO |
| `down <ip>` | **para de enviar HELLO e descarta HELLOs e LSAs dele (novo)**; derruba a vizinhança, novo LSA |
| `up <ip>` | retoma HELLO; enlace só volta após **novo HELLO válido** bidirecional |
| `custo <ip> <n>` | altera custo (1–65535), LSA imediato; gravar no `roteadores.txt` para manter consistência |
| `add <ip> <custo>` | **(novo: obrigatório gravar)** adiciona vizinho e atualiza `roteadores.txt`; ativa só quando o outro lado também configurar |
| `del <ip>` | **(novo)** remove vizinho, atualiza `roteadores.txt`, derruba vizinhança, novo LSA |
| `send <ip> <msg> [ttl]` | envia DATA (TTL 0–255, padrão 16) |
| `replay <vizinho> <origem> dup` | **(novo)** reenvia ao vizinho o LSA armazenado de `<origem>` com a **sequência original** (duplicado) |
| `replay <vizinho> <origem> old [seq]` | **(novo)** idem com **sequência menor** (padrão `seq-1`, mesmos enlaces) |
| `help`, `sair` | — |

Observações do `replay`:
- `<origem>` pode ser qualquer roteador da LSDB (inclusive o próprio).
- Montar o texto a partir do registro da LSDB (`#origem;seq*v;c...`) e enviar só para aquele vizinho. Logar `LSA_REENVIADO_TESTE`.
- Lado receptor deve logar `LSA_DESCARTADO | origem | SEQ=n | DUPLICADO/ANTIGO` e **não** fazer flood.

### 4.8 Log (`logger.py`)
Formato: `HH:MM:SS.mmm | TIPO | origem | descrição`. Tipos:
`HELLO_ENVIADO`, `HELLO_RECEBIDO`, `HELLO_DESCARTADO`, `VIZINHO_ATIVO`, `VIZINHO_INATIVO`, `LSA_GERADO`, `LSA_ACEITO`, `LSA_DESCARTADO` (duplicado/antigo/vizinho inativo/enlace desativado/próprio/malformado), `LSA_ENCAMINHADO`, `LSA_REENVIADO_TESTE`, `LSA_EXPIRADO`, `LSDB_ATUALIZADA`, `DIJKSTRA_EXECUTADO`, `ROTA_NOVA`/`ROTA_REMOVIDA`/`ROTA_ALTERADA`, `DATA_ENVIADA`, `DATA_ENCAMINHADA`, `DATA_RECEBIDO`, `DATA_DESCARTADA`, `MSG_MALFORMADA`, `ENLACE_DESATIVADO`/`ENLACE_ATIVADO`, `CUSTO_ALTERADO`, `VIZINHO_ADICIONADO`/`VIZINHO_REMOVIDO`.
Flag `--quiet-hello` para não poluir a tela (continua no arquivo).

---

## 5. Ambiente de testes

### 5.1 Local (desenvolvimento)
No macOS, criar IPs de loopback:
```bash
for i in 2 3 4 5 6; do sudo ifconfig lo0 alias 127.0.0.$i up; done
```
Cada roteador na sua pasta (por causa de `roteadores.txt`/`seq.txt` fixos):
```bash
cd topologia/r1 && python ../../src/router.py --ip 127.0.0.1
```
Alternativa: Docker com rede bridge (um container por roteador).

### 5.2 Topologia proposta (adaptar aos IPs do laboratório)
```
            10/10
     R1 ─────────── R2
  5→ │ ←7           │ 2/2
     │              │
     R3 ─────────── R4 ──── R6 (entra no cenário B, 6/6)
      \    7/7      │ 4/4  /
   13/13 \          │     / 3/3
           \──────  R5 ──/
```
- `R1→R3 = 5`, `R3→R1 = 7` → **custo assimétrico**.
- R1→R4: via R2 = 12, via R3 = 12 → **empate** (mostra a regra de desempate).
- R1→R5: via R2-R4 = 16 (2 intermediários); via R3 = 18.

`roteadores.txt` de R1:
```
192.168.1.2;10
192.168.1.3;5
```
Calcular **à mão** as tabelas esperadas de cada roteador (vai para o relatório).

### 5.3 Testes unitários
- Parser: válidas, sem vizinhos, IP inválido, custo 0/65536/texto, seq 0/2147483648, TTL 256, > 1200 bytes, `\n` no fim, DATA com `;`.
- Dijkstra: topologia acima, aresta unidirecional (não usar), assimetria, empate, nó isolado, próximo salto inativo.

---

## 6. Cenários do relatório – como executar cada um

Para cada cenário: **comportamento esperado, resultado observado, LSAs relevantes, LSDB antes/depois, tabela antes/depois, trecho de log, captura Wireshark**.

| | Cenário | Como provocar | O que mostrar |
|---|---|---|---|
| A | Convergência inicial | Ligar R1–R5 | HELLOs, vizinhanças, LSAs, LSDB completa, tabelas = calculadas à mão |
| B | Novo roteador | Subir R6 com `roteadores.txt` com R4/R5; em R4 e R5 rodar `add 192.168.1.6 <custo>` (grava o arquivo) | só ativa quando os dois lados configuram; sincronização imediata da LSDB em R6; `[NOVA]` rota para R6 em todos |
| C | Falha de enlace | `down 192.168.1.4` em R2 | R2 cai na hora; R4 detecta após 15 s; LSAs sem o enlace; R1→R4 passa a ser via R3. Mostrar R2 descartando HELLO/LSA de R4 |
| D | Falha de roteador | `Ctrl+C` em R4 | vizinhos detectam em 15 s; enlaces de R4 deixam de ser usados (checagem bidirecional) antes do LSA de R4 expirar (30 s); depois `LSA_EXPIRADO` |
| E | Recuperação | Reiniciar R4 / `up` no enlace | seq de R4 continua do `seq.txt` (ex.: 23 → 24); nova vizinhança; rotas voltam. Opcional: mostrar o que acontece sem `seq.txt` (descartado como antigo) |
| F | LSAs antigos e duplicados | `replay 192.168.1.2 192.168.1.5 dup` e `replay 192.168.1.2 192.168.1.5 old` em R1; também acontece naturalmente no ciclo R1-R2-R4-R3; e o próprio LSA voltando | `LSA_DESCARTADO … DUPLICADO/ANTIGO/PRÓPRIO`, sem flood, validade não renovada (idade continua subindo na `lsdb`) |
| G | Alteração de custo | `custo 192.168.1.2 1` em R1 | LSA imediato, Dijkstra, `[ALTERADA]` R1→R4 vira 3 via R2 e R1→R5 vira 7 |
| H | TTL insuficiente | Em R1: `send 192.168.1.5 teste 1` (morre em R4) e `send 192.168.1.5 teste 0` (morre em R2); comparar com TTL 2 (chega) | log `DATA_DESCARTADA … TTL esgotado` no roteador certo; captura mostrando o TTL em cada salto |

### Wireshark
- Filtro: `udp.port == 6000`.
- Regras de coloração pelo 1º byte do payload:
  - HELLO: `udp.port == 6000 && udp.payload[0] == 0x40` (`@`)
  - LSA: `udp.port == 6000 && udp.payload[0] == 0x23` (`#`)
  - DATA: `udp.port == 6000 && udp.payload[0] == 0x21` (`!`)
- Uma captura `.pcapng` por cenário (`capturas/A_convergencia.pcapng`, ...).
- Capturar na própria máquina de cada roteador (switch não repassa tráfego dos outros).

---

## 7. Interoperabilidade – combinar com os outros grupos

**Resolvido pela nova definição:** TTL na origem (não decrementa), faixa do TTL (0–255), descarte do próprio LSA, nome `seq.txt`.

**Ainda a combinar / confirmar com o professor (urgente):**
1. **Aceitar LSA de vizinho ativo ou de qualquer configurado?** (corpo × pág. 7). Isso muda o que é descartado.
2. **Desempate aleatório ou menor IP?** (não quebra interoperabilidade, mas muda as tabelas esperadas no relatório).
3. **Limites de custo (1–65535) e seq (≤ 2147483647)** valem para todos?
4. HELLO: exigir `IP_ORIGEM == IP do datagrama`? (proposta: sim).
5. HELLO/LSA sem vizinhos (`@IP`, `#IP;SEQ`) são válidos? (proposta: sim).
6. LSA repassado = datagrama original inalterado (proposta: sim).
7. Sem espaços, sem `\n` final, separadores exatamente `@ # ! ; *`; DATA pode conter `;` no texto.
8. Sincronização inclui o próprio LSA (proposta: sim).

Teste mínimo entre grupos: duas máquinas de grupos diferentes trocando HELLO/LSA, conferindo LSDB, DATA nos dois sentidos e `replay` de um para o outro.

---

## 8. Relatório técnico (PDF)

1. Introdução e objetivo
2. **Arquitetura**: threads, fluxo de recebimento/despacho, diagrama
3. **Estruturas de dados**: vizinhos, LSDB, `max_seq`, tabela de rotas, temporizadores (5/10/15/30 s), `seq.txt`
4. Formato e validação das mensagens (com os limites adotados)
5. Flooding, sincronização e regras de descarte (duplicado, antigo, próprio, enlace desativado)
6. **Dijkstra**: pseudocódigo, grafo bidirecional, desempate, próximo salto ativo, gatilho por assinatura
7. Encaminhamento de DATA e semântica do TTL (*k* intermediários ⇒ TTL ≥ *k*)
8. **Topologia de testes** (desenho, IPs, custos, `roteadores.txt` de cada nó, tabelas esperadas)
9. **Cenários A–H**
10. Interoperabilidade e decisões adotadas nos pontos ambíguos (citar a pág. 7)
11. Conclusão e limitações
Anexo: como executar e lista de comandos.

---

## 9. Cronograma revisado (5 dias)

| Dia | Data | Tarefas |
|---|---|---|
| 1 | sex 13/11 | **Perguntar ao professor sobre a pág. 7** e avisar a turma; `protocol.py` com os novos limites + testes; socket, HELLO, vizinhança, `seq.txt`, LSA local, log |
| 2 | sáb 14/11 | Recebimento de LSA, flooding, descartes, expiração, sincronização; Dijkstra + diff |
| 3 | dom 15/11 | DATA/TTL, todos os comandos (`add/del` gravando arquivo, `replay dup/old`); teste local com 5–6 roteadores |
| 4 | seg 16/11 | Teste em 4+ máquinas reais e **com outro grupo**; rodar cenários A–H com capturas e logs |
| 5 | ter 17/11 | Relatório, revisão, **ensaio da apresentação** (cada um explica cada módulo) |
| — | qua 18/11 | Entrega + demonstração |

### Divisão sugerida (até 4 pessoas)
- **P1:** `protocol.py` (parser/limites) + testes + Wireshark
- **P2:** HELLO, vizinhança, temporizadores, `seq.txt`, `add/del/down/up`
- **P3:** LSDB, flooding, descartes, expiração, sincronização, `replay`
- **P4:** Dijkstra, tabela/diff, DATA/TTL, CLI
- Todos: relatório e revisão cruzada do código — o sorteado tem de explicar **qualquer** parte.

---

## 10. Checklist final

- [ ] UDP porta 6000, UTF-8, ≤ 1200 bytes, sem `\n`; limites de custo/seq/TTL validados
- [ ] HELLO a cada 5 s; vizinhança bidirecional; timeout 15 s
- [ ] LSA a cada 10 s e em toda mudança; `seq.txt` gravado **antes** do envio; reinício continua do gravado + 1
- [ ] LSA aceito só de vizinho ativo (ou configurado, conforme resposta do professor); descarta duplicado/antigo sem flood e sem renovar validade
- [ ] LSA com o próprio IP de origem descartado sem processar/encaminhar
- [ ] Flood para todos os ativos exceto o remetente
- [ ] Sincronização completa da LSDB ao formar vizinhança (com HELLO imediato antes)
- [ ] Expiração em 30 s; `max_seq` preservado
- [ ] Dijkstra próprio; só roda se a topologia mudou; aresta só com as duas pontas; próximo salto sempre ativo; desempate conforme regra; sem rota para si
- [ ] Tabela destaca rotas novas/removidas/alteradas; LSDB e tabela exibidas separadamente
- [ ] DATA: TTL opcional 0–255 (padrão 16); origem não decrementa; descarte com motivo (sem rota / TTL 0)
- [ ] Comandos: lsdb, rotas, down (descarta HELLO e LSA) / up, custo, add/del (gravando `roteadores.txt`), send com TTL, replay dup/old para um vizinho
- [ ] Log na tela e em arquivo com todos os eventos
- [ ] Mensagens malformadas descartadas e registradas
- [ ] Testado em ≥ 4 máquinas e com outro grupo
- [ ] Cenários A–H documentados + `.pcapng` de cada um
- [ ] Relatório PDF + código + capturas entregues
- [ ] Todos ensaiaram explicar protocolo, flooding, LSDB, Dijkstra e encaminhamento
