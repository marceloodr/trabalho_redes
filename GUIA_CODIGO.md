# Guia do código para a apresentação

Uso interno do grupo: como explicar o código e onde mexer se pedirem alterações
durante a demonstração. As referências `arquivo:linha` valem para a versão atual de `src/`.

---

## 1. Explicação em 2 minutos

> Cada computador roda um processo `src/main.py`, que é um roteador. Ele abre um socket UDP
> na porta 6000, fazendo bind no próprio IP, e usa três threads: **recepção** (lê os datagramas),
> **temporizadores** (a cada 0,5 s chama `Router.tick()`) e **linha de comando**.
> Todo o estado fica num objeto `Router`, protegido por um único `RLock`.
>
> Com **HELLO** a cada 5 s, o roteador descobre quais vizinhos configurados estão vivos e
> se a vizinhança é bidirecional. Quando a vizinhança sobe ou cai, ou quando um custo muda,
> ele gera um **LSA** novo (SEQ+1, gravado no `seq.txt` antes de enviar) e o manda aos
> vizinhos ativos. Quem recebe um LSA novo guarda na **LSDB** e repassa a todos os vizinhos
> ativos, menos quem mandou (**flooding**). Duplicados e antigos são descartados pelo SEQ.
>
> Com a LSDB, cada roteador monta o grafo, onde uma aresta só vale se os dois lados a
> anunciam, e roda o **Dijkstra** implementado por nós. Assim obtém custo e próximo salto
> para cada destino. As mensagens **DATA** seguem essa tabela, e o TTL é decrementado a
> cada roteador intermediário.

---

## 2. Mapa dos arquivos

| Arquivo | O que faz | Quando olhar |
|---|---|---|
| [`main.py`](src/main.py) | argumentos, cria as threads, interpreta os comandos (`run_command`) | novo comando, mudar a ajuda |
| [`router.py`](src/router.py) | **núcleo**: HELLO, vizinhança, LSA local, recepção de LSA, flooding, DATA, comandos | quase toda alteração de comportamento |
| [`lsdb.py`](src/lsdb.py) | LSDB, `max_seq`, novo/duplicado/antigo, expiração, assinatura | regras de SEQ e expiração |
| [`dijkstra.py`](src/dijkstra.py) | grafo bidirecional, Dijkstra, desempate, diferença entre tabelas | cálculo de rotas |
| [`protocol.py`](src/protocol.py) | parse e format de HELLO/LSA/DATA, limites, 1200 bytes | formato das mensagens |
| [`settings.py`](src/settings.py) | temporizadores, limites, desempate, regra do HELLO | **primeiro lugar** para ajustes simples |
| [`transport.py`](src/transport.py) | socket UDP e thread de recepção | problemas de rede |
| [`config.py`](src/config.py) | lê e grava o `roteadores.txt` | formato do arquivo |
| [`seqstore.py`](src/seqstore.py) | lê e grava o `seq.txt` (com `fsync`) | persistência do SEQ |
| [`logger.py`](src/logger.py) | `router.log` e filtro da tela (`tudo`/`sem-hello`/`nada`) | eventos de log |
| [`views.py`](src/views.py) | tabelas impressas (`lsdb`, `rotas`, `vizinhos`) | mudar o que aparece na tela |

---

## 3. Fluxos principais (o que dizer e onde está)

### 3.1 Inicialização
- [`main.py:134`](src/main.py#L134) `main()`: lê o `roteadores.txt` e cria `Logger`, `Router` e `UdpTransport`.
  Depois liga `router.sender = transport.send`, para que o `Router` não dependa de socket
  (por isso os testes usam uma rede simulada).
- [`router.py:73`](src/router.py#L73) `start()`: gera o primeiro LSA, ainda **sem enlaces**, e envia HELLO.
- [`main.py:167`](src/main.py#L167): a thread de temporizadores chama `tick()` a cada 0,5 s.

### 3.2 Temporizadores: `tick()` ([`router.py:83`](src/router.py#L83))
| Ação | Linha | Valor (`settings.py`) |
|---|---|---|
| envia HELLO a todos os vizinhos com enlace ligado | 89–91 | `HELLO_INTERVAL = 5` |
| vizinho ativo sem HELLO há mais de 15 s → inativo | 93–95 | `NEIGHBOR_TIMEOUT = 15` |
| LSA remoto sem versão nova há mais de 30 s → removido | 97–103 | `LSA_MAX_AGE = 30` |
| renova o LSA local (SEQ+1, mesmo sem mudança) | 105–106 | `LSA_INTERVAL = 10` |

### 3.3 Recepção: `handle_datagram()` ([`router.py:112`](src/router.py#L112))
1. `protocol.decode`: no máximo 1200 bytes, UTF-8 e sem `\n` no final.
2. `protocol.parse`: o primeiro caractere define o tipo (`@` HELLO, `#` LSA, `!` DATA).
3. Se algo falhar, registra `MSG_DESCARTADA` com o motivo e descarta.
4. `sender_ip` é o IP **real** de quem enviou (`recvfrom`). Isso é diferente do `IP_ORIGEM`
   de um LSA repassado.

### 3.4 HELLO e vizinhança ([`router.py:132`](src/router.py#L132))
- Descarta se o `IP_ORIGEM` for diferente do remetente (linha 133, regra opcional em `settings.py`),
  se não for vizinho configurado (136) ou se o enlace estiver desativado por `down` (140).
- Atualiza `last_hello` (144).
- **Bidirecional**: o HELLO dele precisa listar o nosso IP (147). Se sim e ainda não estava
  ativo, chama `_neighbor_up`; se ele deixou de nos listar, chama `_neighbor_down`.
- `_neighbor_up` ([155](src/router.py#L155)):
  1. envia um **HELLO imediato**, para o outro lado também nos ativar antes de receber nossos LSAs;
  2. gera um LSA novo com o enlace;
  3. **sincroniza**: manda ao novo vizinho todos os LSAs da LSDB.
- `Neighbor` ([33](src/router.py#L33)): `enabled` é o enlace lógico (comandos `down`/`up`);
  `active` é a vizinhança confirmada por HELLO. São coisas diferentes.

### 3.5 LSA local: `_originate_lsa()` ([`router.py:254`](src/router.py#L254))
- SEQ+1, **grava o `seq.txt` antes de enviar** (260), anuncia só os vizinhos **ativos** (263),
  instala na própria LSDB, envia a todos os ativos e chama `_recompute()`.
- É disparado na inicialização, a cada 10 s, quando um vizinho fica ativo ou inativo,
  quando um custo muda e quando um vizinho é removido.

### 3.6 Recepção de LSA: `_handle_lsa()` ([`router.py:176`](src/router.py#L176))
O LSA passa por estas checagens, nesta ordem:
1. remetente é vizinho configurado (179), com enlace ligado (181) e **ativo** (183);
2. `IP_ORIGEM` diferente do nosso IP (186);
3. `lsdb.check()`: SEQ maior que o `max_seq` daquela origem, senão é **duplicado** (igual)
   ou **antigo** (menor) e é descartado (189–193).

Se passar: `install` na LSDB (195) → **flooding** do texto original a todos os ativos, menos o
remetente (201–205) → `_recompute()`.

**Por que o flooding não entra em loop?** Cada roteador repassa um dado SEQ uma vez só.
Quando a mesma cópia volta por outro caminho, ela já é duplicada e é descartada sem repasse.

### 3.7 LSDB ([`lsdb.py`](src/lsdb.py))
- `entries`: a versão válida mais recente de cada origem.
- `max_seq`: o maior SEQ já aceito de cada origem. **Nunca é apagado**, nem quando o LSA expira.
  Assim, um LSA antigo que ainda circule não volta a ser aceito.
- `expire()` ([58](src/lsdb.py#L58)): só uma versão **nova** renova o prazo, porque duplicados
  nem chegam ao `install`.
- `signature()` ([73](src/lsdb.py#L73)): o conjunto de nós e de (origem, vizinho, custo).
  A renovação periódica só troca o SEQ, então a assinatura não muda e o Dijkstra não roda.

### 3.8 Dijkstra ([`dijkstra.py`](src/dijkstra.py))
- `build_graph` ([20](src/dijkstra.py#L20)): a aresta u→v, com o custo anunciado **por u**,
  só existe se o LSA de v também lista u. Isso dá a verificação bidirecional e os custos assimétricos.
- `shortest_paths` ([34](src/dijkstra.py#L34)): Dijkstra clássico com `heapq` como fila de prioridade.
  Além de `dist`, guarda `first_hops[v]`, o **conjunto** de vizinhos da origem pelos quais se
  chega a v com custo mínimo:
  - saindo da origem, o primeiro salto é o próprio v; depois, o v herda o de u (56);
  - caminho melhor substitui o conjunto (57–60); caminho de mesmo custo une os conjuntos (61–62);
  - como os custos são > 0, quando v sai da fila todos os seus predecessores ótimos já saíram,
    então o conjunto está completo.
- `compute_routes` ([68](src/dijkstra.py#L68)):
  - só sai da origem por vizinhos ativos (80) e não cria rota para si (85);
  - **desempate** (90–96): `aleatorio` sorteia, mas mantém o próximo salto anterior se ele
    continua ótimo, para a rota não aparecer como "alterada" sem motivo; `menor_ip` escolhe o menor IP;
  - `options` = quantos saltos empatam. É o "(empate entre 2)" da tabela.
- `diff_routes` ([104](src/dijkstra.py#L104)): compara as tabelas e marca [NOVA], [ALTERADA] e [REMOVIDA].
- `_recompute` ([`router.py:275`](src/router.py#L275)) só chama o Dijkstra se a assinatura mudou,
  e imprime a tabela quando há mudanças.

### 3.9 DATA e TTL ([`router.py:214`](src/router.py#L214))
- Se o destino é o nosso IP, `_deliver` mostra a mensagem. Senão, `_forward` ([225](src/router.py#L225)):
  - sem rota, ou próximo salto inativo → `DATA_DESCARTADA (sem rota)`;
  - a **origem envia sem decrementar** (`originated_here=True`);
  - um intermediário descarta se o TTL for 0, senão faz TTL−1 e encaminha (238–242).
- Resultado: k roteadores intermediários exigem TTL ≥ k.
- No `parse_data` ([`protocol.py:152`](src/protocol.py#L152)), `split(";", 4)` faz com que só os
  4 primeiros `;` separem campos, então a mensagem pode conter `;`.

### 3.10 Comandos ([`main.py:67`](src/main.py#L67) → `router.cmd_*`)
| Comando | Método | O que faz |
|---|---|---|
| `down <ip>` | `cmd_down` ([349](src/router.py#L349)) | `enabled=False`: para o HELLO, descarta HELLO e LSA dele e, se estava ativo, gera LSA sem o enlace |
| `up <ip>` | `cmd_up` ([360](src/router.py#L360)) | `enabled=True` e manda HELLO; só fica ativo com o HELLO bidirecional |
| `custo <ip> <n>` | `cmd_cost` ([371](src/router.py#L371)) | grava o `roteadores.txt` e gera LSA |
| `add` / `del` | `cmd_add` / `cmd_del` ([383](src/router.py#L383), [398](src/router.py#L398)) | altera e grava o `roteadores.txt` |
| `send <ip> [ttl=N] <msg>` | `cmd_send` ([328](src/router.py#L328)) | monta o DATA (ID sequencial por execução) e chama `_forward` |
| `replay <viz> <origem> dup\|old [seq]` | `cmd_replay` ([407](src/router.py#L407)) | reenvia um LSA da LSDB com o mesmo SEQ ou com SEQ menor (cenário F) |

---

## 4. Perguntas prováveis e respostas curtas

| Pergunta | Resposta |
|---|---|
| Por que o HELLO imediato ao ativar a vizinhança? | O outro lado ainda nos vê como inativo e descartaria nossos LSAs da sincronização. Com o HELLO imediato, ele nos ativa primeiro. |
| Por que a aresta só vale se os dois LSAs a anunciam? | Num `down`, só um lado retira o enlace na hora. Com a checagem, todos param de usar a aresta assim que o primeiro LSA sem ela chega, sem esperar os 15 s do outro lado. |
| Por que gravar o `seq.txt` antes de enviar? | Se o processo cair logo depois do envio, ao reiniciar ele continua do valor gravado + 1, e os vizinhos não descartam o novo LSA como antigo. |
| E se apagarem o `seq.txt`? | O roteador recomeça em 1 e os outros descartam seus LSAs como antigos até o SEQ passar o valor guardado, ou até os outros reiniciarem. |
| Por que `max_seq` não é apagado na expiração? | Para um LSA antigo que ainda circule não ser aceito como novo depois da expiração. |
| Por que duplicados não renovam a validade? | Só uma versão nova prova que a origem está viva; uma cópia atrasada, não. |
| Por que a renovação periódica não roda o Dijkstra? | Ela só troca o SEQ. Os enlaces e custos são os mesmos, então a assinatura é igual e a tabela não mudaria. |
| Como o empate é tratado? | `first_hops` guarda todos os primeiros saltos ótimos; a escolha é aleatória, mas mantém a anterior se ela continua ótima. |
| O Dijkstra usa biblioteca? | Não. `heapq` é só a fila de prioridade; o algoritmo está em `shortest_paths`. |
| Por que um `RLock` só? | Três threads mexem no mesmo estado. Um lock único evita condições de corrida. Ele é reentrante porque um método com lock chama outro que também usa o lock. |
| Por que bind no IP e não em `0.0.0.0`? | Para os datagramas saírem com o IP do roteador como origem, que é o IP que os vizinhos esperam. Isso também permitiu rodar 6 roteadores numa máquina só nos testes. |
| Diferença entre `enabled` e `active`? | `enabled` é o enlace lógico, controlado pelo usuário (`down`/`up`). `active` é a vizinhança confirmada por HELLO bidirecional. |
| Quando um vizinho fica inativo? | Após 15 s sem HELLO válido, imediatamente num `down` do nosso lado, ou se o HELLO dele deixar de nos listar. |
| Como evitar loop no flooding? | Pelo SEQ: cada LSA é repassado uma vez, e a cópia repetida é descartada como duplicada. Além disso, não repassamos ao remetente. |

---

## 5. Alterações que podem pedir (e como fazer)

> Depois de qualquer alteração: `python3 -m unittest discover -s tests`. Alguns testes verificam
> exatamente o comportamento original; se a alteração for proposital, explique que o teste
> correspondente falhar é o esperado (indicado abaixo em **Teste afetado**).
>
> Para a alteração valer, **reinicie o roteador** (Ctrl+C e rode de novo, na mesma pasta).

### 5.1 Ajustes em `settings.py` (sem mexer na lógica)

| Pedido | Onde | Mudança |
|---|---|---|
| Mudar intervalo do HELLO / LSA / timeout / expiração | [`settings.py:12-15`](src/settings.py#L12) | trocar os números |
| TTL padrão diferente | [`settings.py:17`](src/settings.py#L17) | `DEFAULT_TTL = 8` |
| Desempate pelo menor IP | [`settings.py:44`](src/settings.py#L44) | `DESEMPATE = "menor_ip"` |
| Aceitar HELLO mesmo com `IP_ORIGEM` diferente do remetente | [`settings.py:47`](src/settings.py#L47) | `EXIGIR_ORIGEM_HELLO_IGUAL_REMETENTE = False` |
| Outro limite de tamanho do datagrama | [`settings.py:10`](src/settings.py#L10) | `MAX_PACKET = ...` |
| Outros limites de custo / SEQ / TTL | [`settings.py:26-28`](src/settings.py#L26) | trocar os números |

Teste afetado: nenhum (os testes fixam o desempate e não dependem desses valores).

### 5.2 A origem também decrementa o TTL
[`router.py:237-242`](src/router.py#L237), em `_forward`: tirar o `if not originated_here:`
para a regra valer em todos os roteadores, inclusive na origem.

```python
        ttl = data.ttl
        if ttl == 0:
            self.log("DATA_DESCARTADA", *ident, "motivo: TTL esgotado (TTL=0)", data.text)
            return False
        ttl -= 1
```
Efeito: agora k intermediários exigem TTL ≥ k + 1, e TTL 0 é descartado já na origem.
**Teste afetado:** `test_H_ttl`.

### 5.3 Aceitar LSA de vizinho configurado mesmo que ainda não esteja ativo
[`router.py:183-184`](src/router.py#L183): apagar estas duas linhas.

```python
        if not n.active:
            return self._drop_lsa(lsa, f"recebido de {sender_ip}, que não é vizinho ativo")
```
Efeito: a sincronização não depende mais do HELLO imediato. O flooding continua indo só para
os ativos, porque a linha 201 não muda. Teste afetado: nenhum.

### 5.4 Flooding também de volta para quem enviou
[`router.py:201`](src/router.py#L201):
```python
        targets = self._active()
```
Efeito: mais tráfego; o remetente descarta a cópia como duplicada. Teste afetado: `test_flooding_not_back_to_sender`.

### 5.5 Rodar o Dijkstra a cada LSA aceito, mesmo sem mudança
[`router.py:277-280`](src/router.py#L277), em `_recompute`: apagar as linhas da assinatura.

```python
        signature = self.lsdb.signature()
        if signature == self._last_signature:
            return
        self._last_signature = signature
```
Teste afetado: `test_periodic_refresh_does_not_rerun_dijkstra`.

### 5.6 Dijkstra por número de saltos (ignorar os custos)
[`dijkstra.py:30`](src/dijkstra.py#L30), em `build_graph`:
```python
                graph[u][v] = 1
```
Testes afetados: os de custo em `test_dijkstra.py` e `test_scenarios.py`.

### 5.7 Aceitar enlace anunciado por um lado só (sem verificação bidirecional)
[`dijkstra.py:29`](src/dijkstra.py#L29): trocar a condição por `if v in topology:`.
Efeito: depois de um `down`, os outros continuam usando a aresta até o outro lado
perceber (15 s). Teste afetado: `test_edge_needs_both_ends`.

### 5.8 Esquecer o maior SEQ quando o LSA expira
[`lsdb.py:62-63`](src/lsdb.py#L62), em `expire`:
```python
        for entry in expired:
            del self.entries[entry.origin]
            self.max_seq.pop(entry.origin, None)
```
Efeito: um LSA antigo que chegue depois da expiração volta a ser aceito, e esse é o motivo
de não fazermos isso. Teste afetado: `test_F_old_after_expiry_still_rejected`, `test_D_router_failure_and_E_recovery`.

### 5.9 Novo comando na linha de comando (exemplo: `seq`, que mostra o SEQ atual)
1. Em [`router.py`](src/router.py), junto dos outros `cmd_*`:
   ```python
       def cmd_seq(self):
           with self.lock:
               return self.my_seq
   ```
2. Em [`main.py`](src/main.py) `run_command`, antes do `elif cmd == "help":` (linha 125):
   ```python
       elif cmd == "seq":
           print(f"Último SEQ usado: {router.cmd_seq()}")
   ```
3. Opcional: uma linha no texto `HELP` ([`main.py:22`](src/main.py#L22)).

Para comandos com argumentos, siga o padrão de `custo`: `need(2, "uso")` e `parse_int(args[1], "nome")`.
Para mostrar um erro ao usuário, use `raise CommandError("mensagem")`.

### 5.10 Comando `caminho <ip>` (mostrar o caminho completo, não só o próximo salto)
1. Em [`dijkstra.py`](src/dijkstra.py), uma função nova que guarda o predecessor de cada nó:
   ```python
   def shortest_path(graph, source, dest):
       """(custo, [source, ..., dest]) ou None se não há caminho."""
       dist, prev = {source: 0}, {source: None}
       heap, done = [(0, source)], set()
       while heap:
           d, u = heapq.heappop(heap)
           if u in done:
               continue
           done.add(u)
           for v, cost in graph.get(u, {}).items():
               if v not in dist or d + cost < dist[v]:
                   dist[v], prev[v] = d + cost, u
                   heapq.heappush(heap, (d + cost, v))
       if dest not in dist:
           return None
       path = [dest]
       while prev[path[-1]] is not None:
           path.append(prev[path[-1]])
       return dist[dest], path[::-1]
   ```
2. Em [`router.py:25`](src/router.py#L25), importar:
   `from dijkstra import build_graph, compute_routes, diff_routes, shortest_path`.
   Depois, junto dos `cmd_*`:
   ```python
       def cmd_path(self, dest):
           with self.lock:
               graph = build_graph(self.lsdb.topology())
               graph[self.my_ip] = {v: c for v, c in graph.get(self.my_ip, {}).items()
                                    if self._is_active(v)}
               result = shortest_path(graph, self.my_ip, dest)
               if result is None:
                   raise CommandError(f"sem caminho para {dest}")
               cost, path = result
               return f"{' -> '.join(path)} (custo {cost})"
   ```
3. Em [`main.py`](src/main.py) `run_command`:
   ```python
       elif cmd == "caminho":
           need(1, "caminho <ip>")
           print(router.cmd_path(args[0]))
   ```
Com empate, mostra um dos caminhos de custo mínimo. Teste afetado: nenhum.

### 5.11 Novo evento no log
Em qualquer ponto do `Router`: `self.log("NOME_DO_EVENTO", campo1, campo2, ...)`. A linha sai
com hora e campos separados por `|`, e vai para o `router.log` e para a tela.
Para esconder um evento da tela no modo `sem-hello`, inclua o nome em `HELLO_EVENTS`
([`logger.py:13`](src/logger.py#L13)).

### 5.12 Mudar o que aparece nas tabelas
Em [`views.py`](src/views.py): `format_routes` (tabela de rotas), `format_lsdb` e `format_neighbors`.
São só formatação de texto; não afetam o protocolo.

### 5.13 Ignorar o `seq.txt` ao reiniciar (para mostrar por que ele é necessário)
[`seqstore.py:11`](src/seqstore.py#L11): fazer `load` retornar `0`. Ao reiniciar, os LSAs saem
com SEQ 1, 2, … e os vizinhos os descartam como antigos. Testes afetados: `test_D_router_failure_and_E_recovery`,
`test_seq_saved_before_send`.

---

## 6. Depurando ao vivo

- `tail -f <pasta>/router.log` mostra cada evento com o motivo: `MSG_DESCARTADA`,
  `HELLO_DESCARTADO`, `LSA_DESCARTADO`, `DATA_DESCARTADA`.
- `vizinhos` mostra, para cada vizinho, o enlace (`enabled`), o estado (`active`) e o último HELLO.
- `lsdb` mostra a versão, o horário e quanto falta para expirar cada LSA, além das origens expiradas.
- No Wireshark: `linkstate.tipo == "LSA" && linkstate.origem == <ip>` segue os LSAs de um roteador.
- Se o roteador não abrir: `Não foi possível abrir UDP …` significa que o `--ip` não é um IP da
  máquina ou que a porta 6000 já está em uso (outro roteador aberto).
