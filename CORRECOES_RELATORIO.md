# Correções finais do relatório

Instruções para aplicar no PC que tem o Wireshark/tshark e o weasyprint instalados
(o mesmo que gerou `relatorio/relatorio.pdf`). São só ajustes de texto em
`scripts/gerar_relatorio.py`: **não** é preciso rodar os cenários nem refazer as capturas.

Antes de começar: `git pull` (traz o `integrantes.txt` atualizado e o novo comentário
de `src/settings.py`).

---

## 1. Cenário B: custo da rota [NOVA] para R6 (texto × tabela)

**Problema.** O quadro "Observado" diz que R1 ganhou a rota [NOVA] para R6 com custo 18,
mas a tabela "R1 – tabela impressa após o add" mostra `127.0.0.6 19 ... [NOVA]`.

**O que aconteceu de fato** (`resultados/B/logs/R1.log` e `resultados/roteadores/r1/terminal.txt`):

```
21:07:53.464 | LSA_ACEITO    | 127.0.0.6 | SEQ=2 | ... #127.0.0.6;2*127.0.0.5;3
21:07:53.464 | ROTA_NOVA     | 127.0.0.6 | custo 19 via 127.0.0.3
21:07:53.464 | LSA_ACEITO    | 127.0.0.4 | SEQ=9 | ... *127.0.0.6;6
21:07:53.465 | ROTA_ALTERADA | 127.0.0.6 | custo 19->18 | via 127.0.0.3->127.0.0.3
```

A rota nasceu com custo 19 (via R5), porque o LSA de R4 com o enlace R4–R6 ainda não tinha
chegado, e 1 ms depois passou para 18. O terminal de R1 imprimiu as duas tabelas: a 1ª com
`[NOVA]` (custo 19) e a 2ª com `[ALTERADA: antes custo 19 via 127.0.0.3]` (custo 18).

**Correção em `scripts/gerar_relatorio.py`:**

a) No fim do quadro "Observado" do cenário B (por volta da linha 706), trocar

```
R1
ganhou a rota [NOVA] para R6 com custo 18 (R1→R2/R3→R4→R6 = 12+6; via R5 seria 16+3 = 19).</div>
```

por

```
R1
ganhou a rota [NOVA] para R6 com custo 19 (via R5: 16+3), porque o LSA de R4 com o enlace R4–R6 ainda não tinha
chegado; 1 ms depois esse LSA chegou e a rota passou a 18 (R1→R2/R3→R4→R6 = 12+6).</div>
```

b) Mostrar as duas tabelas de R1 lado a lado e deixar a LSDB de R6 numa linha própria.
Trocar o bloco (por volta da linha 714)

```python
{side_by_side(("R1 – tabela impressa após o add", highlight_table(terminal_table("R1", t_add))),
              ("R6 – LSDB após a sincronização", term_html(snap("B", "depois_add_lsdb_R6", "lsdb"))))}""")
```

por

```python
{side_by_side(("R1 – 1ª tabela após o add (rota nova, custo 19)", highlight_table(terminal_table("R1", t_add))),
              ("R1 – 1 ms depois (custo 18)", highlight_table(terminal_table("R1", t_add, nth=2))))}
{side_by_side(("R6 – LSDB após a sincronização", term_html(snap("B", "depois_add_lsdb_R6", "lsdb"))), ("", ""))}""")
```

**Conferir no PDF:** a 1ª tabela mostra `127.0.0.6 19 ... [NOVA]` e a 2ª mostra
`127.0.0.6 18 ... [ALTERADA: antes custo 19 via 127.0.0.3]`.

---

## 2. Cenário G: frase sobre a LSDB de R2

**Problema.** Abaixo das tabelas "R2 – LSDB antes" e "R2 – LSDB depois da mudança", a frase diz:
"Só a entrada de 127.0.0.1 mudou: SEQ 18 → 19…". Mas as próprias tabelas mostram que
o SEQ de **todas** as origens avançou (renovação periódica de 10 s): R2 19→20, R3 19→20,
R4 21→22, R5 19→20, R6 14→15. O que mudou só em R1 foram os **enlaces**.

**Correção em `scripts/gerar_relatorio.py`** (por volta da linha 821), trocar

```
<p>Só a entrada de 127.0.0.1 mudou: SEQ 18 → 19 e o enlace 127.0.0.2;10 → 127.0.0.2;1.</p>""")
```

por

```
<p>Nos enlaces, só a entrada de 127.0.0.1 mudou: 127.0.0.2;10 → 127.0.0.2;1 (SEQ 18 → 19). As demais origens
apenas avançaram o SEQ pela renovação periódica, com os mesmos enlaces.</p>""")
```

---

## 3. Capa: sobrenome da Cristina

Já corrigido em `relatorio/integrantes.txt` (vem no `git pull`). Basta regerar o PDF.

**Conferir no PDF:** a capa lista "Cristina Einsfeld".

---

## 4. Seção 10: justificativa dos limites de custo e SEQ

**Motivo.** O enunciado só fixa o TTL (0 a 255) e diz que os custos são inteiros positivos.
Os limites de custo e SEQ foram escolhidos pelo grupo e agora têm justificativa técnica
(mesma explicação do comentário em `src/settings.py`).

**Correção em `scripts/gerar_relatorio.py`** (por volta da linha 842), trocar a linha da tabela

```
<tr><td>Limites dos campos</td><td>custo de 1 a 65535 (16 bits), SEQ de 1 a 2147483647 (inteiro de 32 bits com sinal)
e TTL de 0 a 255, como na definição. Valores fora desses limites tornam a mensagem malformada.</td></tr>
```

por

```
<tr><td>Limites dos campos</td><td>a definição fixa só o TTL (0 a 255) e que custos são inteiros positivos. O grupo
adotou custo de 1 a 65535 (16 bits, como a métrica de interface do OSPF) e SEQ de 1 a 2147483647 (maior inteiro de
32 bits com sinal, o <i>MaxSequenceNumber</i> do OSPF; a um LSA a cada 10 s levaria cerca de 680 anos para esgotar).
Assim qualquer grupo, em qualquer linguagem, representa os valores sem estouro. Valores fora desses limites tornam
a mensagem malformada.</td></tr>
```

---

## Regerar e conferir

```bash
python3 scripts/gerar_relatorio.py
```

Conferir em `relatorio/relatorio.pdf`:

- [ ] Cenário B: texto com custo 19 → 18 e as duas tabelas de R1 (19 [NOVA] e 18 [ALTERADA]).
- [ ] Cenário G: frase nova ("Nos enlaces, só a entrada de 127.0.0.1 mudou…").
- [ ] Capa: "Cristina Einsfeld".
- [ ] Seção 10: linha "Limites dos campos" com a justificativa do OSPF.
- [ ] Nenhuma tabela ou bloco cortado no meio por causa das mudanças de tamanho.

Depois: apagar este arquivo (`CORRECOES_RELATORIO.md`), fazer commit de
`scripts/gerar_relatorio.py`, `relatorio/relatorio.html` e `relatorio/relatorio.pdf`, e dar push.
