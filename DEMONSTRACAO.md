# Checklist da demonstração

Roteiro para o computador do grupo (macOS): é a mesma máquina que já rodou os cenários,
fez as capturas e gerou o relatório, então Python, Wireshark e o dissector já estão instalados.

## Antes do dia

- [ ] `git pull` para ter a versão final do código
- [ ] Combinar com os outros grupos a topologia: quem é vizinho de quem e o custo em cada sentido
- [ ] Combinar com os outros grupos quem vai derrubar e reiniciar roteadores nos cenários D e E
      (cada computador roda um roteador só; se levarmos outro computador, ele precisa estar sem VPN)
- [ ] Ensaiar os cenários A–H (tabela abaixo)
- [ ] Todos sabem explicar `router.py` (HELLO, LSA, flooding, DATA) e `dijkstra.py`
- [ ] Todos sabem rodar os testes depois de mexer no código: `python3 -m unittest discover -s tests`

## No laboratório: rede

- [ ] VPN desligada
- [ ] Anotar o IP da máquina: `ifconfig en0` (Wi-Fi; se estiver no cabo, ver a interface certa em `ifconfig`)
- [ ] `ping` para as máquinas dos vizinhos funcionando
- [ ] Na primeira execução, aceitar o aviso do macOS para o Python receber conexões de entrada
      (nos testes no loopback esse aviso não aparece)

## No laboratório: roteador

- [ ] Editar `topologia/r1/roteadores.txt` (ou a pasta do roteador que formos) com os IPs reais:
  ```
  IP_vizinho;custo
  ```
- [ ] O vizinho também lista a nossa máquina no `roteadores.txt` dele (senão o enlace não fica ativo)
- [ ] Iniciar o roteador com o IP exato da interface:
  ```bash
  python3 src/main.py --ip <IP do en0> --dir topologia/r1
  ```
- [ ] Em outro terminal, acompanhar o log completo:
  ```bash
  tail -f topologia/r1/router.log
  ```
- [ ] `log sem-hello` para tirar os HELLOs da tela
- [ ] `vizinhos` mostra todos os vizinhos como ATIVO

## No laboratório: Wireshark

- [ ] Se o Mac foi reiniciado desde os testes, liberar a captura sem root: `sudo bash scripts/preparar_mac.sh`
- [ ] Perfil **TF-Redes** selecionado (canto inferior direito → Profile)
- [ ] Capturar na interface da rede (`en0`), **não** na `lo0` usada nos testes; filtro de captura `udp port 6000`
- [ ] HELLO em azul, LSA em verde, DATA em laranja

## Cenários

| ✓ | Cenário | Comando | O que mostrar |
|---|---|---|---|
| [ ] | A – Convergência | subir todos os roteadores | `vizinhos`, `lsdb`, `rotas`; tabelas conferem com o cálculo à mão |
| [ ] | B – Novo roteador | ligar o roteador novo; `add <ip> <custo>` nos vizinhos dele | HELLOs descartados antes do `add`; sincronização da LSDB; rota [NOVA] em todos |
| [ ] | C – Falha de enlace | `down <ip>` → esperar ~15 s → `up <ip>` | rotas [ALTERADA] na hora; o outro lado marca inativo após 15 s; volta no primeiro HELLO |
| [ ] | D – Falha de roteador | Ctrl+C num roteador | após 15 s os vizinhos o declaram inativo; após 30 s o LSA expira (`lsdb` mostra "Origens expiradas") |
| [ ] | E – Recuperação | reiniciar **na mesma pasta** (não apagar o `seq.txt`) | primeiro LSA com SEQ gravado + 1, aceito pelos outros; rotas voltam |
| [ ] | F – LSA antigo/duplicado | `replay <vizinho> <origem> dup` e `replay <vizinho> <origem> old` | `LSA_DESCARTADO` no vizinho, sem flooding e sem renovar a validade |
| [ ] | G – Custo | `custo <ip> <n>` | novo LSA; só muda o sentido alterado; rotas [ALTERADA] |
| [ ] | H – TTL | `send <ip> ttl=0 oi`, `ttl=1`, `ttl=2`…; `send` para um IP sem rota | descarte no roteador certo (TTL esgotado / sem rota); TTL diminuindo a cada salto na captura |

## Se algo não funcionar

| Sintoma no `router.log` | Causa provável | O que fazer |
|---|---|---|
| nada chega | VPN, firewall ou IP errado no `--ip` | conferir VPN, o aviso do firewall do macOS e o `ping` |
| Wireshark vazio | captura na `lo0` | trocar para `en0` |
| `HELLO_DESCARTADO` … não é vizinho configurado | falta a linha no `roteadores.txt` | adicionar com `add <ip> <custo>` |
| `HELLO_DESCARTADO` com IP de origem diferente | máquina do outro grupo com várias interfaces | em `src/settings.py`: `EXIGIR_ORIGEM_HELLO_IGUAL_REMETENTE = False` e reiniciar |
| `MSG_DESCARTADA` | mensagem fora do formato (ex.: `\n` no final) | mostrar o motivo no log e o datagrama no Wireshark ao outro grupo |
| vizinho nunca fica ATIVO | só um lado configurou o enlace | os dois lados precisam listar um ao outro |
| LSAs de um roteador reiniciado descartados como antigos | `seq.txt` apagado | esperar a sequência passar o valor guardado ou reiniciar os outros |

Lembrete para interpretar outros grupos: no nosso roteador a origem **não** decrementa o TTL,
então k roteadores intermediários exigem TTL ≥ k.
