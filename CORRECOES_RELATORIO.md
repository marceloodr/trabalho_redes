# Correções no relatório – instruções para o Claude

Este arquivo descreve as correções a aplicar no relatório técnico (`relatorio/relatorio.pdf`) e em alguns
arquivos do código. Leia tudo antes de começar e aplique na ordem. Quando terminar, apague este arquivo.

## Regras

- **Não rode `scripts/cenarios.py`.** Ele refaz as capturas e os resultados, o que muda horários, números de
  quadro e SEQs citados abaixo. As capturas (`capturas/*.pcapng`) e os resultados (`resultados/`) ficam como estão.
- O relatório é gerado por `scripts/gerar_relatorio.py` a partir de `resultados/` e `capturas/`. **Corrija o
  gerador e regenere**; não edite `relatorio/relatorio.html` à mão. Requisitos: `tshark` (Wireshark) e
  `weasyprint` (`pip install weasyprint`; no macOS também `brew install pango`).
- Os números de linha abaixo são aproximados (versão do commit `9ed054a`). Localize pelo texto citado.
- O comportamento do roteador **não muda**. As mudanças em `src/` só removem opções e comentários.

---

## Parte 1 – Remover as menções à última página do enunciado

A última página do enunciado ("Decisões novas para você validar") não deveria ter ficado no documento, então
nada do que entregamos deve mencioná-la. Também não deve aparecer nada que só faria sentido para quem a leu:
"texto principal", "pág. 7", "última página", "pontos ambíguos" e as opções alternativas que vieram dela.

### 1.1 `src/settings.py`

- Linha ~19: trocar o comentário
  `# Limites dos campos (pág. 7 da definição; TTL 0-255 também está no texto principal)` por
  `# Limites dos campos: TTL 0-255 vem da definição; custo (16 bits) e SEQ (inteiro de 32 bits com sinal) foram escolhidos pelo grupo`
- Substituir o bloco inteiro de "Políticas" (do comentário `# Políticas para os pontos em que a definição é
  ambígua` até `EXIGIR_ORIGEM_HELLO_IGUAL_REMETENTE = True`) por:

```python
# ---------------------------------------------------------------------------
# Desempate entre caminhos de mesmo custo no Dijkstra:
#   "aleatorio" – sorteia entre os próximos saltos empatados (pedido na definição)
#   "menor_ip"  – escolhe o menor IP; usado nos testes automatizados para que
#                 o resultado seja sempre o mesmo
# ---------------------------------------------------------------------------
DESEMPATE = "aleatorio"

# Exigir que o IP_ORIGEM do HELLO seja o IP de onde veio o datagrama
EXIGIR_ORIGEM_HELLO_IGUAL_REMETENTE = True
```

Ou seja: as constantes `ACEITAR_LSA_DE` e `SALTAR_SEQ_PROPRIA` deixam de existir.

### 1.2 `src/router.py`

- Em `Router.__init__`, remover o parâmetro `accept_lsa_from=None` e a linha
  `self.accept_lsa_from = accept_lsa_from or settings.ACEITAR_LSA_DE`.
- Em `_handle_lsa`, trocar `if self.accept_lsa_from == "ativo" and not n.active:` por `if not n.active:`.
- Em `_handle_lsa`, remover o `if settings.SALTAR_SEQ_PROPRIA ...` e as 3 linhas dentro dele. O bloco fica:

```python
        if lsa.origin == self.my_ip:
            return self._drop_lsa(lsa, f"LSA com o próprio IP de origem (via {sender_ip})")
```

- Confirmar com `grep -rn "ACEITAR_LSA_DE\|SALTAR_SEQ\|accept_lsa_from" src tests scripts` que não sobrou nada.

### 1.3 `README.md`

- Na árvore de "Organização do código", trocar
  `settings.py   temporizadores, limites e políticas (pontos ambíguos da definição)` por
  `settings.py   temporizadores, limites e modo de desempate`.
- Substituir a seção inteira `### Políticas configuráveis (src/settings.py)` (a tabela com "Alternativa (pág. 7)"
  e o parágrafo seguinte) por:

```markdown
### Desempate (`src/settings.py`)

`DESEMPATE = "aleatorio"` sorteia entre os próximos saltos de mesmo custo, como pede a definição. Quando uma rota
empatada é recalculada e o próximo salto anterior continua entre os melhores, ele é mantido, para a rota não aparecer
como "alterada" sem motivo. `"menor_ip"` escolhe sempre o menor IP; os testes automatizados usam esse modo para ter
um resultado previsível.
```

### 1.4 `scripts/gerar_relatorio.py`

- **Sumário da capa** (linha ~481): trocar `Decisões nos pontos ambíguos e limitações` por
  `Decisões de implementação e limitações`.
- **Tabela de módulos** (linha ~501): trocar
  `temporizadores, limites e as políticas dos pontos ambíguos da definição` por
  `temporizadores, limites e modo de desempate`.
- **Seção 10** (linha ~826, de `add("""<h2 class="scen">10. Decisões nos pontos ambíguos` até o fim do parágrafo
  "Outras decisões: ..."): substituir o título, o parágrafo de abertura, a tabela, o parágrafo do HELLO imediato e o
  de "Outras decisões" por este HTML. O parágrafo **Limitações** que vem depois continua igual.

```html
<h2 class="scen">10. Decisões de implementação e limitações</h2>
<p>Pontos em que a definição deixa a escolha ao grupo:</p>
<table class="grid"><tr><th>Ponto</th><th>Decisão</th></tr>
<tr><td>Limites dos campos</td><td>custo de 1 a 65535 (16 bits), SEQ de 1 a 2147483647 (inteiro de 32 bits com sinal)
e TTL de 0 a 255, como na definição. Valores fora desses limites tornam a mensagem malformada.</td></tr>
<tr><td>Empate no Dijkstra</td><td>sorteio entre os próximos saltos de mesmo custo; se o próximo salto anterior continua
entre os melhores, ele é mantido, para a rota não aparecer como alterada sem motivo</td></tr>
<tr><td>HELLO</td><td>aceito só se o <code>IP_ORIGEM</code> for o IP de onde veio o datagrama</td></tr>
<tr><td>Flooding</td><td>o LSA é repassado como o datagrama original, sem alteração</td></tr>
<tr><td>Sincronização</td><td>ao formar a vizinhança, o roteador envia um HELLO imediato e só depois os LSAs (o próprio,
recém-gerado, e todos os outros válidos da LSDB). Como um LSA só é aceito de vizinho ativo, o HELLO imediato faz o
outro lado ativar a vizinhança antes de os LSAs chegarem (visto nos cenários A, B e E).</td></tr></table>
```

---

## Parte 2 – Capa

1. Remover a linha **Entregáveis** da tabela da capa (linhas ~474–475, de `<tr><td><b>Entregáveis</b></td>` até
   `(<code>capturas/*.pcapng</code>)</td></tr>`). A tabela termina na linha **Linguagem**, que deve fechar com `</table>`.
2. `relatorio/integrantes.txt`: a integrante "Cristina" está sem sobrenome. **Pergunte ao usuário** qual é o nome
   completo; não invente.

---

## Parte 3 – Legendas do Wireshark que não batem com os pacotes

### 3.1 Cenário D (linha ~748): o filtro mostra os pacotes errados

Hoje o filtro usa a janela `frame.time_relative > 13 && < 18`. Nela só aparecem os quadros 130–133, que são a
renovação periódica do R1 (SEQ 14), e o R1 nem é vizinho do R4. Os LSAs dos vizinhos já sem o enlace com o R4
estão entre 12,08 s e 12,40 s. Trocar o filtro e a legenda por:

```python
{wireshark_table("D_falha_roteador.pcapng", 'ip.src==127.0.0.4 || (linkstate.tipo=="LSA" && linkstate.origem == ip.src && linkstate.origem in {127.0.0.2 127.0.0.3 127.0.0.5 127.0.0.6} && frame.time_relative > 11.5 && frame.time_relative < 12.5)', limit=20,
                 caption="últimos LSAs repassados por R4 antes da falha e, cerca de 12 s depois, os primeiros LSAs gerados por R6, R3, R5 e R2 já sem o enlace com R4")}
```

(`linkstate.origem == ip.src` mostra só o envio feito pelo próprio autor do LSA, sem as cópias repassadas.)

**Conferir no PDF:** 12 linhas. Primeiro os quadros 3, 5, 7, 17, 18 e 19 (enviados pelo R4). Depois:

| Quadro | De → para | LSA |
|---|---|---|
| 96 | R6 → R5 | `#127.0.0.6;10*127.0.0.5;3` |
| 103, 104 | R3 → R1, R5 | `#127.0.0.3;15*127.0.0.1;7*127.0.0.5;13` |
| 112, 113 | R5 → R3, R6 | `#127.0.0.5;15*127.0.0.3;13*127.0.0.6;3` |
| 117 | R2 → R1 | `#127.0.0.2;15*127.0.0.1;10` |

Se o `tshark` recusar a sintaxe `in {...}` ou a comparação `linkstate.origem == ip.src`, troque por
`(ip.src==127.0.0.2 || ip.src==127.0.0.3 || ip.src==127.0.0.5 || ip.src==127.0.0.6) && linkstate.origem == ip.src`
ou equivalente, e confira o resultado com a tabela acima.

### 3.2 Cenário F (linha ~789): legenda diz "quatro LSAs", a tabela tem cinco

O quadro 17 (2,028 s) é a renovação periódica do R1 com SEQ 18, que o R2 **aceitou** (log do R2 às 21:09:41.225).
O quadro 31 é o `replay` desse mesmo LSA, descartado como duplicado. Manter a tabela e trocar a legenda por:

```python
caption="LSAs enviados por R1 a R2. Os de origem 127.0.0.5 (SEQ 19, 18 e 1) são de teste. O LSA de R1 com SEQ 18 aparece duas vezes: a primeira é a renovação periódica normal (aceita por R2); a segunda, 1 s depois, é o replay com o mesmo SEQ (descartado como duplicado)"
```

---

## Parte 4 – LSDB faltando em cenários

A definição pede "alterações da LSDB" em cada cenário. Os instantâneos já existem em `resultados/`; só não entraram
no relatório.

- **Cenário C** (bloco que termina na linha ~734): acrescentar depois do último `side_by_side`:

```python
{side_by_side(("R1 – LSDB após a queda do enlace", term_html(snap("C", "t19s_lsdb_R1", "lsdb"))))}
<p>O LSA de R2 (SEQ 11) passou a anunciar só 127.0.0.1;10, e o de R4 (SEQ 13) não lista mais 127.0.0.2.</p>
```

- **Cenário G** (linha ~808): acrescentar depois do último `side_by_side`. O instantâneo `F/depois_R2` foi tirado
  2,8 s antes do comando `custo`, então serve como "antes":

```python
{side_by_side(("R2 – LSDB antes (fim do cenário F)", term_html(snap("F", "depois_R2", "lsdb"))),
              ("R2 – LSDB depois da mudança", term_html(snap("G", "depois_lsdb_R2", "lsdb"))))}
<p>Só a entrada de 127.0.0.1 mudou: SEQ 18 → 19 e o enlace 127.0.0.2;10 → 127.0.0.2;1.</p>
```

  Antes de escrever esse parágrafo, confira nos dois arquivos que a entrada de 127.0.0.1 é mesmo SEQ 18 com
  `127.0.0.2;10` e SEQ 19 com `127.0.0.2;1`.

- **Cenário H** (fim do "Observado", linha ~818): acrescentar a frase
  `A LSDB e as tabelas não mudam neste cenário; elas só são consultadas para encaminhar.`

---

## Parte 5 – Ajustes menores

### 5.1 Rótulos de tempo

Os rótulos usam o tempo de espera planejado no roteiro, não o medido. Isso cria contradições aparentes: no C,
"19 s após o down" aparece ao lado de "inativo há 24 s", mas o instantâneo foi tirado 21 s depois. Calcule o
tempo real a partir da 1ª linha de cada arquivo de `resultados/`, que termina com o horário
(ex.: `# C – t19s – R4 (127.0.0.4) – 21:08:28.956`). A função `secs()` já existe no script:

```python
def snap_time(cid, name):
    with open(os.path.join(RES, cid, name + ".txt"), encoding="utf-8") as f:
        return f.readline().rsplit(" – ", 1)[1].strip()

def after(cid, name, t_event):
    return f"{secs(snap_time(cid, name)) - secs(t_event):.0f} s"
```

Use nos rótulos. Valores esperados:

| Rótulo atual | Instantâneo | Correto |
|---|---|---|
| C "R2 – vizinhos 3 s após o down" | `C/t03s_R2` | 4 s |
| C "R4 – vizinhos 19 s após o down" | `C/t19s_R4` | 21 s |
| D "R1 – LSDB 5 s após a falha" / "tabela 5 s após" | `D/t05s_R1` | 6 s |
| D "R1 – tabela 19 s após" / "R2 – tabela 19 s após" | `D/t19s_R1`, `D/t19s_R2` | 22 s |
| D "R1 – LSDB 34 s após a falha" | `D/t34s_R1` | 38 s |

O evento de referência é `t_down` no C e `t_kill` no D.

### 5.2 Cenário D, texto do "Observado" (linha ~744)

"R1→R6 passou de 18 (via R4) para 21 (via R3→R5→R6)" pode ser lido como se o próximo salto fosse R4, mas o próximo
salto era R3. Trocar por:
`R1→R6 passou de 18 (caminho R1→R3→R4→R6) para 21 (R1→R3→R5→R6), com um passo intermediário de 19 quando R6 retirou o enlace com R4 antes dos demais`.

### 5.3 Topologia (linha ~601)

A coluna "IP no laboratório" lista 192.168.1.x, que são só IPs de exemplo. Trocar o cabeçalho por
`IP de exemplo (rede real)`.

### 5.4 Quebra de "(empate entre 2)"

Nas linhas de tabelas lado a lado com 3 colunas, "(empate entre 2)" quebra em 3 linhas: R1 no cenário A
(linhas ~681–685) e "R1 – tabela 5 s após" no D (linhas ~752–754). Corrija de uma destas formas:

- passar esses `side_by_side` para 2 células por linha; ou
- impedir a quebra na coluna de observação via CSS (`white-space: nowrap`).

Confira no PDF que a observação fica numa linha só.

---

## Parte 6 – Fora da entrega

- `PLANO.md` e `Definição_TF_20262.pdf` falam da última página do enunciado e **não fazem parte da entrega**.
  Não os inclua no material enviado. Não apague o `PLANO.md` sem perguntar ao usuário. Se a entrega for o link do
  repositório, avise o usuário de que o histórico do git ainda contém os dois arquivos.
- Opcional, só se `resultados/` for entregue: os arquivos `resultados/roteadores/*/terminal.txt` contêm o caminho
  absoluto do computador onde os cenários rodaram (`/Users/.../trabalho_redes/`). Remova esse prefixo deixando o
  caminho relativo, ou não entregue `resultados/`, que não é exigido.

---

## Verificação final

1. `python3 -m unittest discover -s tests` → 39 testes OK.
2. `python3 scripts/gerar_relatorio.py` → regenera `relatorio/relatorio.html` e `relatorio/relatorio.pdf`.
3. Extrair o texto do PDF (`pdftotext relatorio/relatorio.pdf -`) e confirmar que **não aparece**: `última página`,
   `ultima pagina`, `texto principal`, `pág. 7`, `ambígu`, `para validar`, `ACEITAR_LSA_DE`, `SALTAR_SEQ`,
   `Entregáveis`, `IP no laboratório`, `quatro LSAs de teste`.
4. Fazer a mesma busca em `src/`, `tests/`, `scripts/`, `wireshark/` e `README.md`. O `PLANO.md` fica de fora.
5. Abrir o PDF e conferir:
   - tabela do cenário D conforme a Parte 3.1;
   - legenda do F;
   - LSDB nos cenários C e G;
   - frase do H;
   - rótulos de tempo da Parte 5.1;
   - capa sem "Entregáveis" e com o nome completo da Cristina.
6. Apagar este arquivo (`CORRECOES_RELATORIO.md`) e fazer um commit, por exemplo:
   `Corrige relatório: legendas do Wireshark, LSDB nos cenários C e G, tempos e seção 10`.
