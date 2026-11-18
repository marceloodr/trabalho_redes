#!/usr/bin/env python3
"""Gera relatorio/relatorio.html (e relatorio.pdf, se o WeasyPrint estiver instalado)
a partir do que scripts/cenarios.py gravou em resultados/ e capturas/.

    python3 scripts/cenarios.py          # 1) roda os cenários e captura
    python3 scripts/gerar_relatorio.py   # 2) monta o relatório

Para o PDF:  pip install weasyprint   (no macOS também: brew install pango)
Integrantes do grupo: uma linha por nome em relatorio/integrantes.txt
"""

import html
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "resultados")
CAP = os.path.join(ROOT, "capturas")
OUT = os.path.join(ROOT, "relatorio")
TSHARK = next((p for p in ("/Applications/Wireshark.app/Contents/MacOS/tshark",
                           shutil.which("tshark") or "") if p and os.path.exists(p)), None)
LUA = os.path.join(ROOT, "wireshark", "linkstate.lua")

TS = re.compile(r"^\d\d:\d\d:\d\d\.\d{3}")
SCEN = {s["id"]: s for s in json.load(open(os.path.join(RES, "cenarios.json"), encoding="utf-8"))}

E = html.escape


# ---------------------------------------------------------------------------
# Leitura das evidências
# ---------------------------------------------------------------------------

def event_time(cid, needle):
    """Horário (HH:MM:SS.mmm) do evento da cronologia que contém `needle`."""
    for line in SCEN[cid]["eventos"]:
        if needle in line:
            return line[:12]
    raise KeyError(needle)


def secs(t):
    h, m, rest = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def snap_time(cid, name):
    """Horário (HH:MM:SS.mmm) gravado na 1ª linha de resultados/<cid>/<name>.txt."""
    with open(os.path.join(RES, cid, name + ".txt"), encoding="utf-8") as f:
        return f.readline().rsplit(" – ", 1)[1].strip()


def after(cid, name, t_event):
    """Tempo real entre o evento e o instantâneo, ex.: "21 s"."""
    return f"{secs(snap_time(cid, name)) - secs(t_event):.0f} s"


def snap(cid, name, cmd=None):
    """Conteúdo de resultados/<cid>/<name>.txt; com `cmd`, só a saída daquele comando."""
    text = open(os.path.join(RES, cid, name + ".txt"), encoding="utf-8").read()
    body = text.split("\n", 1)[1]
    if cmd is None:
        return body.strip("\n")
    blocks = re.split(r"^\$ ", body, flags=re.M)
    for b in blocks:
        if b.startswith(cmd + "\n"):
            return b[len(cmd) + 1:].strip("\n")
    raise KeyError(cmd)


def logs(cid, routers, include=None, exclude=r"HELLO_(ENVIADO|RECEBIDO)", start=None, end=None,
         limit=None, strip_text=False):
    """Linhas de log de vários roteadores, intercaladas por horário e marcadas com o nome."""
    rows = []
    for r in routers:
        path = os.path.join(RES, cid, "logs", f"{r}.log")
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8"):
            line = line.rstrip("\n")
            t = line[:12]
            if start and t < start or end and t > end:
                continue
            if include and not re.search(include, line):
                continue
            if exclude and re.search(exclude, line):
                continue
            if strip_text:
                line = re.sub(r" \| [#@!]\S*$", "", line)
            rows.append((t, r, line))
    rows.sort(key=lambda x: x[0])
    if limit and len(rows) > limit:
        rows = rows[:limit] + [("", "", f"... (+{len(rows) - limit} linhas)")]
    return "\n".join(f"{r:<2} │ {l}" if r else l for _, r, l in rows)


def terminal_table(router, after, nth=1):
    """Tabela "(atualizada)" que o roteador imprimiu no terminal depois de `after`
    (com os destaques [NOVA]/[ALTERADA]/[REMOVIDA])."""
    lines = open(os.path.join(RES, "roteadores", router.lower(), "terminal.txt"),
                 encoding="utf-8").read().splitlines()
    i = next(k for k, l in enumerate(lines) if TS.match(l) and l[:12] >= after)
    found = 0
    while i < len(lines):
        if "TABELA DE ROTEAMENTO (atualizada)" in lines[i]:
            found += 1
            if found == nth:
                block = []
                for l in lines[i:]:
                    if not l.strip() or TS.match(l):
                        break
                    block.append(l)
                return "\n".join(block)
        i += 1
    raise KeyError(f"tabela de {router} após {after}")


TSHARK_FIELDS = ["frame.number", "frame.time_relative", "ip.src", "udp.srcport", "ip.dst",
                 "udp.dstport", "frame.len", "linkstate.tipo", "linkstate.texto"]


def tshark_rows(capture, display_filter, limit=None):
    if not TSHARK:
        return []
    cmd = [TSHARK, "-r", os.path.join(CAP, capture), "-T", "fields", "-E", "separator=\t",
           "-E", "occurrence=f"]
    if not lua_installed():
        cmd[1:1] = ["-X", f"lua_script:{LUA}"]
    if display_filter:
        cmd += ["-Y", display_filter]
    for f in TSHARK_FIELDS:
        cmd += ["-e", f]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    rows = [l.split("\t") for l in out.splitlines() if l]
    total = len(rows)
    if limit:
        rows = rows[:limit]
    return rows, total


def lua_installed():
    return os.path.exists(os.path.expanduser("~/.local/lib/wireshark/plugins/linkstate.lua"))


def tshark_detail(capture, display_filter):
    """Árvore de protocolos + bytes de um pacote (como o painel inferior do Wireshark)."""
    rows, _ = tshark_rows(capture, display_filter, 1)   # -c conta pacotes lidos, não filtrados
    cmd = [TSHARK, "-r", os.path.join(CAP, capture), "-Y", f"frame.number=={rows[0][0]}",
           "-O", "ip,udp,linkstate", "-x"]
    if not lua_installed():
        cmd[1:1] = ["-X", f"lua_script:{LUA}"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    keep = []
    skip = re.compile(r"^\s+(\[|\.|0|Header|Differentiated|Identification|Flags|Fragment|Time to|"
                      r"Protocol:|Header Checksum|Checksum|UDP payload|Stream|Total Length|Version|"
                      r"Family|Explicit|Total)")
    for l in out.splitlines():
        if skip.match(l) or "bits)" in l and l.startswith("Frame"):
            if l.startswith("Frame"):
                keep.append(l.split(",")[0] + f"  ({capture})")
            continue
        keep.append(l)
    return "\n".join(keep).strip()


# ---------------------------------------------------------------------------
# Blocos HTML
# ---------------------------------------------------------------------------

def pre(text, cls="log"):
    return f'<pre class="{cls}">{E(text)}</pre>'


def highlight_table(text):
    """Tabela de rotas do terminal com as marcas coloridas (como na tela)."""
    return term_html(text)
    out = []
    for l in text.splitlines():
        s = E(l)
        if "[NOVA]" in l:
            s = f'<span class="nova">{s}</span>'
        elif "[ALTERADA" in l:
            s = f'<span class="alterada">{s}</span>'
        elif "[REMOVIDA" in l:
            s = f'<span class="removida">{s}</span>'
        out.append(s)
    return '<pre class="tab">' + "\n".join(out) + "</pre>"


IPRE = r"\d+\.\d+\.\d+\.\d+"


def term_html(text):
    """Converte a saída de rotas/lsdb/vizinhos do terminal numa tabela HTML
    (mesmo conteúdo, sem quebrar linha), mantendo os destaques [NOVA]/[ALTERADA]/[REMOVIDA]."""
    lines = text.splitlines()
    title = next((l.strip() for l in lines if l.strip()), "")
    rows, notes = [], []
    if title.startswith("TABELA DE ROTEAMENTO"):
        head = ["Destino", "Custo total", "Próximo salto", ""]
        for l in lines:
            m = re.match(rf"^\s+({IPRE})\s+(\d+|-)\s+({IPRE}|-)\s*(.*)$", l)
            if not m:
                continue
            obs = m.group(4).strip()
            cls = ("nova" if "[NOVA]" in obs else "alterada" if "[ALTERADA" in obs
                   else "removida" if "[REMOVIDA" in obs else "")
            rows.append((cls, [m.group(1), m.group(2), m.group(3), obs]))
        if not rows:
            notes.append("(sem rotas)")
    elif title.startswith("LSDB"):
        head = ["Origem", "SEQ", "Recebido em", "Expira em", "Enlaces (vizinho;custo)"]
        for l in lines:
            m = re.match(rf"^\s+({IPRE})\s+(\d+)\s+(\S+)\s+(local|\d+ s)\s+(.*)$", l)
            if m:
                rows.append(("", list(m.groups())))
            elif "Origens expiradas" in l:
                notes.append(l.strip())
    elif title.startswith("VIZINHOS"):
        head = ["Vizinho", "Custo", "Enlace", "Estado", "Último HELLO"]
        for l in lines:
            m = re.match(rf"^\s+({IPRE})\s+(\d+)\s+(ativado|DESATIVADO)\s+(ATIVO|inativo)\s+(.*)$", l)
            if m:
                cls = "removida" if m.group(3) == "DESATIVADO" or m.group(4) == "inativo" else ""
                rows.append((cls, list(m.groups())))
    else:
        return pre(text, "tab")
    th = "".join(f"<th>{E(h)}</th>" for h in head)
    body = "".join(f'<tr class="{c}">' + "".join(f"<td>{E(x)}</td>" for x in r) + "</tr>" for c, r in rows)
    note = "".join(f'<div class="tnote">{E(n)}</div>' for n in notes)
    return f'<div class="term"><div class="ttitle">{E(title)}</div><table class="term">{th}{body}</table>{note}</div>'


def wireshark_table(capture, display_filter, limit=None, caption=None):
    res = tshark_rows(capture, display_filter, limit)
    if not res:
        return "<p><em>tshark indisponível</em></p>"
    rows, total = res
    head = ("<tr><th>Nº</th><th>Tempo (s)</th><th>IP origem</th><th>Porta</th><th>IP destino</th>"
            "<th>Porta</th><th>Bytes</th><th>Tipo</th><th>Conteúdo do datagrama (UTF-8)</th></tr>")
    body = []
    for r in rows:
        r += [""] * (len(TSHARK_FIELDS) - len(r))
        num, t, src, sp, dst, dp, ln, kind, text = r
        body.append(f'<tr class="{kind.lower()}"><td>{num}</td><td>{float(t):.3f}</td><td>{src}</td>'
                    f"<td>{sp}</td><td>{dst}</td><td>{dp}</td><td>{ln}</td><td>{kind}</td>"
                    f'<td class="payload">{E(text)}</td></tr>')
    more = f" — {len(rows)} de {total} pacotes" if limit and total > len(rows) else ""
    cap = (f'<div class="wscap">Wireshark: <code>{E(capture)}</code>, filtro '
           f'<code>{E(display_filter)}</code>{more}' + (f". {caption}" if caption else "") + "</div>")
    table = cap + f'<table class="ws">{head}{"".join(body)}</table>'
    # legenda, cabeçalho e linhas na mesma página (tabelas curtas)
    return f'<div class="avoid">{table}</div>' if len(rows) <= 25 else table


def side_by_side(*cells):
    """Blocos lado a lado: cells = (título, html)."""
    tds = "".join(f'<td><div class="cell-title">{E(t)}</div>{h}</td>' for t, h in cells)
    return f'<table class="sbs"><tr>{tds}</tr></table>'


# ---------------------------------------------------------------------------
# Tabelas esperadas (calculadas à mão) × observadas
# ---------------------------------------------------------------------------

def parse_routes(text):
    routes = {}
    for l in text.splitlines():
        m = re.match(r"\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+)\s+(\d+\.\d+\.\d+\.\d+)", l)
        if m:
            routes[m.group(1)] = (int(m.group(2)), m.group(3))
    return routes


def ip(n):
    return f"127.0.0.{n}"


# destino: (custo, {próximos saltos aceitos}) – topologia do cenário A
EXPECTED_A = {
    "R1": {2: (10, {2}), 3: (5, {3}), 4: (12, {2, 3}), 5: (16, {2, 3})},
    "R2": {1: (10, {1}), 3: (9, {4}), 4: (2, {4}), 5: (6, {4})},
    "R3": {1: (7, {1}), 2: (9, {4}), 4: (7, {4}), 5: (11, {4})},
    "R4": {1: (12, {2}), 2: (2, {2}), 3: (7, {3}), 5: (4, {5})},
    "R5": {1: (16, {4}), 2: (6, {4}), 3: (11, {4}), 4: (4, {4})},
}

# derivação manual de cada linha (texto do relatório)
DERIV_A = {
    ("R1", 4): "R1→R2→R4 = 10+2 = 12; R1→R3→R4 = 5+7 = 12 (empate)",
    ("R1", 5): "via R2–R4: 12+4 = 16; via R3–R4: 12+4 = 16; R3 direto: 5+13 = 18",
    ("R2", 3): "R2→R4→R3 = 2+7 = 9; R2→R1→R3 = 10+5 = 15",
    ("R2", 5): "R2→R4→R5 = 2+4 = 6",
    ("R5", 2): "R5→R4→R2 = 4+2 = 6; via R3: 13+7+2 = 22",
    ("R3", 2): "R3→R4→R2 = 7+2 = 9; R3→R1→R2 = 7+10 = 17",
    ("R3", 5): "R3→R4→R5 = 7+4 = 11; direto = 13",
    ("R4", 1): "R4→R2→R1 = 2+10 = 12; R4→R3→R1 = 7+7 = 14",
    ("R5", 1): "R5→R4→R2→R1 = 4+2+10 = 16; R5→R3→R1 = 13+7 = 20",
    ("R5", 3): "R5→R4→R3 = 4+7 = 11; direto = 13",
}


def expected_vs_observed():
    rows, ok_all = [], True
    for r, exp in EXPECTED_A.items():
        obs = parse_routes(snap("A", f"convergida_{r}", "rotas"))
        for d, (cost, hops) in exp.items():
            o = obs.get(ip(d))
            ok = o is not None and o[0] == cost and int(o[1].rsplit(".", 1)[1]) in hops
            ok_all &= ok
            exp_hop = " ou ".join(f"R{h}" for h in sorted(hops))
            obs_txt = f"{o[0]} via R{o[1].rsplit('.', 1)[1]}" if o else "—"
            deriv = DERIV_A.get((r, d), "enlace direto")
            rows.append(f"<tr><td>{r}</td><td>R{d}</td><td>{cost}</td><td>{exp_hop}</td>"
                        f"<td>{obs_txt}</td><td class='{'ok' if ok else 'fail'}'>{'✔' if ok else '✘'}</td>"
                        f"<td class='small'>{E(deriv)}</td></tr>")
        extra = set(obs) - {ip(d) for d in exp}
        ok_all &= not extra
    head = ("<tr><th>Roteador</th><th>Destino</th><th>Custo esperado</th><th>Próx. salto esperado</th>"
            "<th>Observado</th><th></th><th>Cálculo</th></tr>")
    return f'<table class="grid">{head}{"".join(rows)}</table>', ok_all


# ---------------------------------------------------------------------------
# Figuras (SVG)
# ---------------------------------------------------------------------------

def topology_svg():
    pos = {1: (90, 60), 2: (430, 60), 3: (90, 270), 4: (430, 270), 5: (260, 430), 6: (620, 430)}
    # (a, b, custo a->b, custo b->a, tracejado?)
    edges = [(1, 2, 10, 10, False), (1, 3, 5, 7, False), (2, 4, 2, 2, False), (3, 4, 7, 7, False),
             (3, 5, 13, 13, False), (4, 5, 4, 4, False), (4, 6, 6, 6, True), (5, 6, 3, 3, True)]
    parts = ['<svg viewBox="0 0 720 490" class="topo" xmlns="http://www.w3.org/2000/svg">']
    for a, b, cab, cba, dashed in edges:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#555" stroke-width="2"{dash}/>')
        for (xa, ya), (xb, yb), c in (((x1, y1), (x2, y2), cab), ((x2, y2), (x1, y1), cba)):
            lx, ly = xa + (xb - xa) * 0.27, ya + (yb - ya) * 0.27
            parts.append(f'<rect x="{lx - 14}" y="{ly - 11}" width="28" height="20" rx="4" fill="#fff" '
                         f'stroke="#bbb"/><text x="{lx}" y="{ly + 4}" class="cost">{c}</text>')
    for n, (x, y) in pos.items():
        fill = "#fde7c8" if n == 6 else "#dbe8fb"
        parts.append(f'<circle cx="{x}" cy="{y}" r="34" fill="{fill}" stroke="#2b5797" stroke-width="2"/>'
                     f'<text x="{x}" y="{y - 3}" class="node">R{n}</text>'
                     f'<text x="{x}" y="{y + 14}" class="nip">.{n}</text>')
    parts.append("</svg>")
    return "".join(parts)


def architecture_svg():
    """Diagrama de módulos/threads (atributos inline: a WeasyPrint não aplica CSS dentro do SVG)."""
    T = 'font-family="Helvetica, Arial, sans-serif" text-anchor="middle"'

    def box(x, y, w, h, title, lines=(), core=False):
        fill, stroke = ("#fff8e8", "#a15c00") if core else ("#eef3fa", "#2b5797")
        out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
               f'<text x="{x + w / 2}" y="{y + 22}" {T} font-size="12.5" font-weight="bold" fill="#17375e">{E(title)}</text>']
        for k, l in enumerate(lines):
            out.append(f'<text x="{x + w / 2}" y="{y + 40 + k * 19}" {T} font-size="10.5" fill="#333">{E(l)}</text>')
        return "".join(out)

    def arrow(x1, y1, x2, y2):
        return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#444" stroke-width="1.6" '
                f'marker-end="url(#ar)"/>')

    parts = ['<svg viewBox="0 0 720 300" style="width:100%;display:block;margin:4pt 0" xmlns="http://www.w3.org/2000/svg">',
             '<defs><marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
             '<path d="M0,0 L8,4 L0,8 z" fill="#444"/></marker></defs>',
             box(10, 20, 190, 62, "Thread de recepção", ["transport.py · recvfrom(6000)"]),
             box(10, 118, 190, 62, "Thread de temporizadores", ["Router.tick() a cada 0,5 s"]),
             box(10, 216, 190, 62, "Thread principal (CLI)", ["main.py · comandos → cmd_*()"]),
             box(262, 20, 230, 258, "Router (router.py)",
                 ["um único RLock protege o estado", "", "handle_datagram → HELLO/LSA/DATA",
                  "vizinhos {ip: Neighbor}", "LSDB + max_seq (lsdb.py)", "routes {destino: Route}",
                  "_originate_lsa · _recompute", "flooding · sincronização · expiração",
                  "encaminhamento de DATA (TTL)"], core=True),
             box(552, 20, 158, 50, "protocol.py", ["parse / format"]),
             box(552, 84, 158, 50, "dijkstra.py", ["grafo + Dijkstra"]),
             box(552, 148, 158, 50, "seqstore / config", ["seq.txt · roteadores.txt"]),
             box(552, 212, 158, 66, "logger / views", ["router.log · tabelas"]),
             arrow(200, 51, 260, 80), arrow(200, 149, 260, 149), arrow(200, 247, 260, 220),
             arrow(492, 50, 550, 45), arrow(492, 112, 550, 109), arrow(492, 173, 550, 173),
             arrow(492, 240, 550, 245), "</svg>"]
    return "".join(parts)


# ---------------------------------------------------------------------------
# Documento
# ---------------------------------------------------------------------------

CSS = """
@page { size: A4; margin: 17mm 15mm 17mm 15mm;
  @bottom-right { content: counter(page) " / " counter(pages); font: 8pt sans-serif; color: #777; }
  @bottom-left { content: "Fundamentos de Redes de Computadores – Trabalho Final"; font: 8pt sans-serif; color: #777; } }
@page :first { @bottom-left { content: none } @bottom-right { content: none } }
body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.42; color: #1d1d1f; }
h1 { font-size: 21pt; margin: 0 0 4pt; color: #17375e; }
h2 { font-size: 14pt; color: #17375e; border-bottom: 1.5px solid #17375e; padding-bottom: 2pt; margin-top: 18pt;
     page-break-after: avoid; }
h2.scen { page-break-before: always; }
h3 { font-size: 11pt; margin: 12pt 0 4pt; color: #2b5797; page-break-after: avoid; }
p { margin: 4pt 0 6pt; text-align: justify; }
code { font-family: Menlo, "DejaVu Sans Mono", monospace; font-size: 8.6pt; background: #f2f2f4; padding: 0 2px; border-radius: 2px; }
pre { font-family: Menlo, "DejaVu Sans Mono", monospace; font-size: 7.1pt; line-height: 1.3; background: #f6f7f9;
      border: 1px solid #dcdfe4; border-radius: 3px; padding: 5pt 6pt; white-space: pre-wrap; word-break: break-all;
      margin: 3pt 0 7pt; }
pre.tab { background: #fbfbf6; font-size: 7.6pt; }
pre.code { background: #f7f5ff; font-size: 7.6pt; }
.nova { color: #137333; font-weight: bold; } .alterada { color: #a15c00; font-weight: bold; }
.removida { color: #b3261e; font-weight: bold; }
table { border-collapse: collapse; }
table.grid { width: 100%; font-size: 8.4pt; margin: 4pt 0 8pt; }
table.grid th, table.grid td { border: 1px solid #ccd; padding: 2pt 4pt; text-align: left; vertical-align: top; }
table.grid th { background: #e8eef7; }
td.ok { color: #137333; font-weight: bold; text-align: center; } td.fail { color: #b3261e; font-weight: bold; }
td.small, .small { font-size: 7.6pt; color: #444; }
table.ws { width: 100%; font-family: Menlo, "DejaVu Sans Mono", monospace; font-size: 6.6pt; margin: 2pt 0 8pt; }
table.ws th { background: #3c3c3c; color: #fff; padding: 2pt 3pt; text-align: left; font-weight: normal; }
table.ws td { padding: 1.4pt 3pt; border-bottom: 1px solid #fff; vertical-align: top; }
table.ws td.payload { word-break: break-all; }
tr.hello td { background: #b0d2ff; } tr.lsa td { background: #a8e6a2; } tr.data td { background: #ffbf66; }
.wscap { font-size: 7.8pt; color: #444; margin-top: 6pt; }
table.sbs { width: 100%; table-layout: fixed; page-break-inside: avoid; margin-bottom: 4pt; }
div.term { background: #fbfbf6; border: 1px solid #dcdfe4; border-radius: 3px; padding: 3pt 4pt; margin: 2pt 0 6pt; }
.ttitle { font: bold 7.4pt Menlo, monospace; color: #333; margin-bottom: 2pt; }
.tnote { font: 6.8pt Menlo, monospace; color: #555; margin-top: 2pt; }
table.term { width: 100%; font-family: Menlo, "DejaVu Sans Mono", monospace; font-size: 6.9pt; }
table.term th { text-align: left; border-bottom: 1px solid #999; padding: 1pt 4pt 1pt 0; font-weight: normal; color: #555; }
table.term td { padding: 0.8pt 4pt 0.8pt 0; vertical-align: top; }
tr.nova td { color: #137333; font-weight: bold; } tr.alterada td { color: #a15c00; font-weight: bold; }
tr.removida td { color: #b3261e; font-weight: bold; } table.sbs td { vertical-align: top; padding: 0 3pt; }
.cell-title { font-size: 8pt; font-weight: bold; color: #2b5797; margin-top: 4pt; }
.box-exp { border-left: 4px solid #2b5797; background: #f1f5fb; padding: 4pt 8pt; margin: 6pt 0; }
.box-obs { border-left: 4px solid #137333; background: #f0f8f1; padding: 4pt 8pt; margin: 6pt 0; }
.box-exp, .box-obs { page-break-inside: avoid; }
.box-exp { page-break-after: avoid; }
.box-exp b, .box-obs b { display: block; font-size: 8.6pt; text-transform: uppercase; letter-spacing: .03em; }
svg.topo { width: 78%; display: block; margin: 4pt auto; }
svg.topo .cost { font: bold 13px sans-serif; text-anchor: middle; fill: #a15c00; }
svg.topo .node { font: bold 18px sans-serif; text-anchor: middle; fill: #17375e; }
svg.topo .nip { font: 12px sans-serif; text-anchor: middle; fill: #444; }
svg.arch { width: 100%; display: block; margin: 4pt 0; }
svg.arch text { font: bold 12px sans-serif; text-anchor: middle; fill: #17375e; }
svg.arch text.s { font: 10px sans-serif; fill: #333; }
svg.arch .box rect { fill: #eef3fa; stroke: #2b5797; stroke-width: 1.4; }
svg.arch .core rect { fill: #fff8e8; stroke: #a15c00; stroke-width: 1.6; }
.cover { margin-top: 40mm; }
.cover .sub { font-size: 12.5pt; color: #444; margin-bottom: 26pt; }
.cover table td { padding: 2pt 10pt 2pt 0; font-size: 10.5pt; vertical-align: top; }
.toc { margin-top: 24pt; font-size: 10pt; } .toc li { margin: 1pt 0; }
ul { margin: 3pt 0 6pt 14pt; padding: 0; } li { margin: 1.5pt 0; }
.avoid { page-break-inside: avoid; }
"""


def members():
    path = os.path.join(OUT, "integrantes.txt")
    if os.path.exists(path):
        names = [l.strip() for l in open(path, encoding="utf-8") if l.strip()]
        if names:
            return "<br>".join(E(n) for n in names)
    return "<em>(preencher em relatorio/integrantes.txt)</em>"


def code_excerpt(path, start_pat, end_pat):
    lines = open(os.path.join(ROOT, path), encoding="utf-8").read().splitlines()
    i = next(k for k, l in enumerate(lines) if re.search(start_pat, l))
    j = next(k for k in range(i + 1, len(lines)) if re.search(end_pat, lines[k]))
    return "\n".join(lines[i:j]).rstrip()


def build():
    exp_table, exp_ok = expected_vs_observed()
    seq_r4 = next(l for l in SCEN["E"]["eventos"] if "seq.txt" in l).split("= ")[1]
    P = []
    add = P.append

    # ---------------- capa ----------------
    add(f"""<div class="cover">
<h1>Roteador Link State inspirado no OSPF</h1>
<div class="sub">Fundamentos de Redes de Computadores – Trabalho Final – Relatório técnico</div>
<table><tr><td><b>Integrantes</b></td><td>{members()}</td></tr>
<tr><td><b>Linguagem</b></td><td>Python 3 (somente biblioteca padrão), sockets UDP na porta 6000</td></tr></table>
<ol class="toc">
<li>Arquitetura da solução</li><li>Estruturas de dados e temporizadores</li>
<li>Protocolo: mensagens e validação</li><li>LSA, flooding, sincronização e expiração</li>
<li>Implementação do Dijkstra</li><li>Encaminhamento de DATA e TTL</li>
<li>Topologia de testes e ambiente de captura</li><li>Capturas do Wireshark</li>
<li>Cenários A–H</li><li>Decisões de implementação e limitações</li><li>Como executar</li></ol>
</div>""")

    # ---------------- 1. arquitetura ----------------
    add(f"""<h2 class="scen">1. Arquitetura da solução</h2>
<p>Cada computador executa um processo <code>src/main.py</code> que atua como roteador. O processo abre um
socket UDP ligado ao IP do roteador na porta 6000 (o bind no IP próprio faz os datagramas saírem com o IP
de origem correto e permite vários roteadores na mesma máquina). Três threads compartilham um único objeto
<code>Router</code>, e todo acesso ao estado passa por um <code>threading.RLock</code>, o que elimina
condições de corrida entre recepção, temporizadores e comandos.</p>
{architecture_svg()}
<table class="grid"><tr><th>Módulo</th><th>Responsabilidade</th></tr>
<tr><td><code>main.py</code></td><td>argumentos (<code>--ip</code>, <code>--dir</code>, <code>--log-tela</code>), criação das threads e interpretação dos comandos</td></tr>
<tr><td><code>router.py</code></td><td>núcleo: HELLO e vizinhança, LSA local, aceitação e flooding de LSAs, sincronização, expiração, Dijkstra sob demanda, DATA e comandos</td></tr>
<tr><td><code>lsdb.py</code></td><td>LSDB (versão mais recente por origem), <code>max_seq</code>, classificação novo/duplicado/antigo, expiração, assinatura da topologia</td></tr>
<tr><td><code>dijkstra.py</code></td><td>grafo bidirecional, Dijkstra próprio, desempate e diferença entre tabelas</td></tr>
<tr><td><code>protocol.py</code></td><td>validação (parse) e montagem (format) de HELLO, LSA e DATA; limites de tamanho e de campos</td></tr>
<tr><td><code>transport.py</code></td><td>socket UDP e laço de recepção (<code>recvfrom</code> → <code>Router.handle_datagram</code>)</td></tr>
<tr><td><code>seqstore.py</code>, <code>config.py</code></td><td>persistência do <code>seq.txt</code> (gravado antes de cada LSA) e do <code>roteadores.txt</code></td></tr>
<tr><td><code>logger.py</code>, <code>views.py</code></td><td>log na tela e em <code>router.log</code>; tabelas de LSDB, rotas e vizinhos</td></tr>
<tr><td><code>settings.py</code></td><td>temporizadores, limites e modo de desempate</td></tr></table>
<p><b>Fluxo de recepção.</b> O datagrama é decodificado em UTF-8 e validado; o primeiro caractere define o tipo
(<code>@</code> HELLO, <code>#</code> LSA, <code>!</code> DATA). Mensagens malformadas, com mais de 1200 bytes
ou terminadas em quebra de linha são descartadas e registradas (<code>MSG_DESCARTADA</code>). O remetente
real do datagrama (<code>addr[0]</code> do <code>recvfrom</code>) é usado para decidir de qual vizinho a
mensagem veio, o que é diferente do <code>IP_ORIGEM</code> de um LSA repassado.</p>""")

    # ---------------- 2. estruturas ----------------
    add("""<h2>2. Estruturas de dados e temporizadores</h2>
<table class="grid"><tr><th>Estrutura</th><th>Tipo</th><th>Conteúdo</th></tr>
<tr><td>Vizinhos</td><td><code>dict ip → Neighbor</code></td><td><code>cost</code> (custo de mim até ele, do <code>roteadores.txt</code>),
<code>enabled</code> (enlace lógico ligado; comandos <code>down</code>/<code>up</code>), <code>active</code> (vizinhança confirmada
por HELLO bidirecional), <code>last_hello</code> (instante do último HELLO válido, relógio monotônico)</td></tr>
<tr><td>LSDB</td><td><code>dict origem → LsaEntry</code></td><td>IP de origem, <code>seq</code>, enlaces <code>{vizinho: custo}</code>,
instante de recebimento da versão válida (monotônico para a expiração e hora de parede para exibição). Inclui o LSA local.</td></tr>
<tr><td>Maior SEQ aceito</td><td><code>dict origem → int</code></td><td><code>LSDB.max_seq</code>: nunca é apagado enquanto o processo roda,
mesmo após a expiração, para descartar anúncios antigos que ainda circulem</td></tr>
<tr><td>Tabela de roteamento</td><td><code>dict destino → Route</code></td><td><code>cost</code>, <code>next_hop</code> (sempre vizinho ativo) e
<code>options</code> (quantos próximos saltos empatam)</td></tr>
<tr><td>Assinatura da topologia</td><td><code>frozenset</code></td><td>conjunto de nós e de triplas (origem, vizinho, custo) dos LSAs válidos;
o Dijkstra só roda quando ela muda</td></tr>
<tr><td>Sequência local</td><td><code>int</code> + <code>seq.txt</code></td><td>último SEQ usado; gravado com <code>fsync</code> e troca atômica do arquivo antes de cada envio</td></tr>
<tr><td>ID de DATA</td><td><code>int</code></td><td>contador por execução (único por origem durante a execução)</td></tr></table>
<p>A thread de temporizadores chama <code>Router.tick()</code> a cada 0,5 s. Cada tick verifica:</p>
<table class="grid"><tr><th>Temporizador</th><th>Valor</th><th>Ação</th></tr>
<tr><td>HELLO</td><td>5 s</td><td>envia <code>@meu_ip*vizinhos_configurados</code> a cada vizinho com enlace ativado</td></tr>
<tr><td>LSA local</td><td>10 s</td><td>gera novo LSA (SEQ+1), mesmo sem mudança; o prazo é reiniciado sempre que um LSA é gerado por evento</td></tr>
<tr><td>Vizinho inativo</td><td>15 s</td><td>vizinho ativo sem HELLO válido há mais de 15 s → <code>VIZINHO_INATIVO</code>, novo LSA, flooding e recálculo</td></tr>
<tr><td>Expiração de LSA</td><td>30 s</td><td>LSA remoto sem versão nova há mais de 30 s é removido da LSDB (o <code>max_seq</code> fica) e as rotas são recalculadas</td></tr></table>""")

    # ---------------- 3. protocolo ----------------
    add("""<h2>3. Protocolo: mensagens e validação</h2>
<table class="grid"><tr><th>Mensagem</th><th>Formato</th><th>Exemplo capturado</th></tr>
<tr><td>HELLO</td><td><code>@IP_ORIGEM*VIZINHO1*VIZINHO2...</code></td><td><code>@127.0.0.1*127.0.0.2*127.0.0.3</code></td></tr>
<tr><td>LSA</td><td><code>#IP_ORIGEM;SEQ*VIZINHO;CUSTO*...</code></td><td><code>#127.0.0.1;5*127.0.0.2;10*127.0.0.3;5</code></td></tr>
<tr><td>DATA</td><td><code>!IP_ORIGEM;IP_DESTINO;ID;TTL;MENSAGEM</code></td><td><code>!127.0.0.1;127.0.0.5;3;2;teste TTL 2</code></td></tr></table>
<p>Validação aplicada a todo datagrama recebido (e ao montar os enviados): UTF-8 válido; no máximo 1200 bytes;
sem quebra de linha no final; todos os endereços IPv4 em notação decimal; custo inteiro de 1 a 65535; SEQ de 1
a 2147483647; TTL de 0 a 255; ID inteiro não negativo. HELLO sem vizinhos (<code>@IP</code>) e LSA sem enlaces
(<code>#IP;SEQ</code>) são válidos. Na DATA, só os quatro primeiros <code>;</code> separam campos, então o texto
pode conter <code>;</code> (testado no cenário H). Um HELLO só é aceito se o <code>IP_ORIGEM</code> for igual ao IP
de onde veio o datagrama e se o emissor for vizinho configurado com enlace ativado.</p>""")

    # ---------------- 4. LSA ----------------
    add(f"""<h2>4. LSA, flooding, sincronização e expiração</h2>
<p><b>Vizinhança.</b> Um HELLO válido de vizinho configurado atualiza <code>last_hello</code>. Se o HELLO nos lista
entre os vizinhos do emissor, a vizinhança é bidirecional e o vizinho passa a ativo. Nesse momento o roteador
(1) envia um HELLO imediato a esse vizinho, para que o outro lado também o considere ativo antes de receber os
LSAs, (2) gera um novo LSA local com o enlace e (3) envia ao novo vizinho todos os LSAs válidos da LSDB
(sincronização). Se um HELLO deixa de nos listar, a vizinhança cai.</p>
<p><b>LSA local.</b> <code>_originate_lsa()</code> incrementa o SEQ, grava o <code>seq.txt</code> <i>antes</i> de enviar,
instala o LSA na LSDB, envia a todos os vizinhos ativos e chama o recálculo. É disparado na inicialização, a cada
10 s e quando um vizinho fica ativo ou inativo, quando um custo muda e quando um vizinho é removido. Ao reiniciar,
o SEQ continua do valor gravado + 1 (cenário E: <code>seq.txt</code> de R4 = {E(seq_r4)}, primeiro LSA após o reinício com SEQ={int(seq_r4) + 1}).</p>
<p><b>Recebimento de LSA</b> (<code>_handle_lsa</code>), na ordem dos testes:</p>
<ul><li>remetente não é vizinho configurado, enlace desativado com ele ou vizinho não ativo → descarta;</li>
<li><code>IP_ORIGEM</code> igual ao próprio IP → descarta sem processar nem encaminhar;</li>
<li><code>SEQ ≤ max_seq[origem]</code> → descarta como <b>duplicado</b> (igual) ou <b>antigo</b> (menor), sem flooding e sem
renovar a validade;</li>
<li>caso contrário, aceita: grava na LSDB com o instante atual, atualiza <code>max_seq</code>, repassa o datagrama original
a todos os vizinhos ativos exceto o remetente e chama o recálculo.</li></ul>
<p><b>Expiração.</b> Cada LSA remoto vale 30 s a partir da última versão nova aceita. Como duplicados e antigos não
chamam <code>install()</code>, eles não renovam o prazo (cenário F mostra o tempo restante continuar caindo).</p>""")

    # ---------------- 5. Dijkstra ----------------
    add(f"""<h2>5. Implementação do Dijkstra</h2>
<p>O cálculo foi implementado pelo grupo; <code>heapq</code> é usado só como fila de prioridade. Três etapas:</p>
<ul><li><b>Grafo bidirecional</b> (<code>build_graph</code>): a aresta u→v, com o custo anunciado por u, só existe se o
LSA de v também lista u. Assim, um enlace só é usado quando as duas pontas o reconhecem, e cada sentido usa o
seu próprio custo (custos assimétricos). Saindo da origem, só entram vizinhos ativos.</li>
<li><b>Dijkstra</b> (<code>shortest_paths</code>): além da distância, guarda para cada nó o conjunto de
<i>primeiros saltos</i> que levam a ele com custo mínimo. Em caso de empate (<code>nova == dist[v]</code>), os
conjuntos são unidos.</li>
<li><b>Tabela</b> (<code>compute_routes</code>): sem rota para si; próximo salto sempre vizinho ativo; empate resolvido
de forma aleatória, mas a escolha anterior é mantida se continua ótima, para a rota não aparecer como "alterada"
sem motivo. <code>diff_routes</code> compara com a tabela anterior e marca linhas <b>[NOVA]</b>, <b>[ALTERADA]</b> e
<b>[REMOVIDA]</b>.</li></ul>
{pre(code_excerpt("src/dijkstra.py", r"^def shortest_paths", r"^def compute_routes"), "code")}
<p><b>Quando roda.</b> <code>_recompute()</code> compara a assinatura da topologia (nós e triplas origem–vizinho–custo)
com a do último cálculo. A renovação periódica só troca o SEQ, então não muda a assinatura e não executa o
Dijkstra. O primeiro cálculo acontece logo após o primeiro LSA local, com o que já existe na LSDB.</p>""")

    # ---------------- 6. DATA ----------------
    add("""<h2>6. Encaminhamento de DATA e TTL</h2>
<p>O comando <code>send &lt;ip&gt; [ttl=N] &lt;texto&gt;</code> monta <code>!origem;destino;ID;TTL;texto</code> com TTL inicial
de 0 a 255 (padrão 16) e usa a tabela disponível no momento. A origem envia ao próximo salto <b>sem decrementar</b>.
Quem recebe faz:</p>
<pre class="code">se destino == meu IP          → exibe "Mensagem de X (ID n): texto"          DATA_RECEBIDO
senão, sem rota (ou próximo salto inativo) → descarta                    DATA_DESCARTADA (sem rota)
senão, TTL == 0               → descarta                                  DATA_DESCARTADA (TTL esgotado)
senão                         → TTL − 1 e envia ao próximo salto          DATA_ENCAMINHADA</pre>
<p>Assim, um caminho com <i>k</i> roteadores intermediários exige TTL inicial ≥ <i>k</i>. No cenário H, R1→R5 passa por
R2 e R4 (k = 2): TTL 0 morre em R2, TTL 1 morre em R4 e TTL 2 chega a R5.</p>""")

    # ---------------- 7. topologia ----------------
    add(f"""<h2>7. Topologia de testes e ambiente de captura</h2>
{topology_svg()}
<p class="small" style="text-align:center">Cada número fica perto do roteador que o anuncia: é o custo no sentido
<i>daquele roteador para o outro</i>. R1→R3 = 5 e R3→R1 = 7 (custo assimétrico). R6 e seus enlaces (tracejado)
entram no cenário B.</p>
<table class="grid"><tr><th>Roteador</th><th>IP de exemplo (rede real)</th><th>IP nos testes</th><th>roteadores.txt</th></tr>
<tr><td>R1</td><td>192.168.1.1</td><td>127.0.0.1</td><td><code>.2;10</code> <code>.3;5</code></td></tr>
<tr><td>R2</td><td>192.168.1.2</td><td>127.0.0.2</td><td><code>.1;10</code> <code>.4;2</code></td></tr>
<tr><td>R3</td><td>192.168.1.3</td><td>127.0.0.3</td><td><code>.1;7</code> <code>.4;7</code> <code>.5;13</code></td></tr>
<tr><td>R4</td><td>192.168.1.4</td><td>127.0.0.4</td><td><code>.2;2</code> <code>.3;7</code> <code>.5;4</code> (+ <code>.6;6</code> pelo comando <code>add</code>)</td></tr>
<tr><td>R5</td><td>192.168.1.5</td><td>127.0.0.5</td><td><code>.3;13</code> <code>.4;4</code> (+ <code>.6;3</code> pelo comando <code>add</code>)</td></tr>
<tr><td>R6</td><td>192.168.1.6</td><td>127.0.0.6</td><td><code>.4;6</code> <code>.5;3</code></td></tr></table>
<p>A topologia foi escolhida para exercitar custos assimétricos (R1–R3), empates (R1→R4 e R1→R5 têm dois caminhos
de mesmo custo), um caminho com dois intermediários para o teste de TTL e um nó extra (R6) para a entrada de roteador.</p>
<p><b>Ambiente.</b> Os cenários foram executados numa única máquina (macOS), com seis processos reais
(<code>src/main.py</code>), cada um com o seu IP de loopback (127.0.0.1 a 127.0.0.6, criados com
<code>ifconfig lo0 alias</code>) e a sua pasta com <code>roteadores.txt</code>, <code>seq.txt</code> e <code>router.log</code>.
Os <code>roteadores.txt</code> são os da pasta <code>topologia/</code>, com 192.168.1.N trocado por 127.0.0.N. O roteiro
<code>scripts/cenarios.py</code> envia os comandos pela entrada padrão de cada roteador, registra as saídas de
<code>lsdb</code>, <code>rotas</code> e <code>vizinhos</code> e captura o tráfego da porta 6000 com o <code>dumpcap</code> do
Wireshark 4.6.9 na interface <code>lo0</code>, gerando um <code>.pcapng</code> por cenário. Os trechos de log deste
relatório foram copiados de <code>resultados/&lt;cenário&gt;/logs/</code>; cada linha começa com o roteador que a gerou.</p>
<h3>Tabelas esperadas (calculadas à mão) × observadas no cenário A</h3>
{exp_table}
<p>Resultado: {"todas as rotas observadas coincidem com o cálculo manual" if exp_ok else "<b>há divergências (✘)</b>"}.
Nos empates, qualquer um dos próximos saltos listados é correto (desempate aleatório).</p>""")

    # ---------------- 8. Wireshark ----------------
    caps = sorted(f for f in os.listdir(CAP) if f.endswith(".pcapng"))
    cap_rows = []
    for c in caps:
        res = tshark_rows(c, None)
        rows = res[0] if res else []
        count = {k: sum(1 for r in rows if len(r) > 7 and r[7] == k) for k in ("HELLO", "LSA", "DATA")}
        cap_rows.append(f"<tr><td><code>capturas/{c}</code></td><td>{len(rows)}</td><td>{count['HELLO']}</td>"
                        f"<td>{count['LSA']}</td><td>{count['DATA']}</td></tr>")
    add(f"""<h2 class="scen">8. Capturas do Wireshark</h2>
<p>Para marcar as mensagens, o grupo escreveu um dissector Lua (<code>wireshark/linkstate.lua</code>) que reconhece
o tráfego da porta UDP 6000 e mostra o tipo (HELLO, LSA, DATA) e cada campo (IP_ORIGEM, SEQ, enlaces, destino,
ID, TTL, mensagem), além de um perfil de cores (<code>wireshark/perfil-TF-Redes</code>): <span style="background:#b0d2ff">HELLO
em azul</span>, <span style="background:#a8e6a2">LSA em verde</span>, <span style="background:#ffbf66">DATA em laranja</span>.
Para usar na interface gráfica: <code>bash wireshark/instalar_perfil.sh</code> e escolher o perfil <i>TF-Redes</i>.
Filtros: <code>linkstate.tipo == "HELLO"</code>, <code>linkstate.tipo == "LSA"</code>,
<code>linkstate.tipo == "DATA"</code>, <code>linkstate.seq</code>, <code>linkstate.ttl</code>. Sem o dissector, os mesmos
pacotes aparecem com <code>udp.port == 6000</code> e o conteúdo fica no painel de bytes.</p>
<p>As tabelas de pacotes deste relatório foram exportadas com o <code>tshark</code> (mesmo motor do Wireshark) e usam as
mesmas cores. Colunas: número do quadro, tempo desde o início da captura, IP e porta UDP de origem e de destino,
tamanho do quadro e conteúdo do datagrama.</p>
<table class="grid"><tr><th>Arquivo</th><th>Pacotes</th><th>HELLO</th><th>LSA</th><th>DATA</th></tr>{"".join(cap_rows)}</table>
<h3>Anatomia de um pacote de cada tipo</h3>
<p>Detalhe de protocolo e bytes, como nos painéis inferiores do Wireshark. Na interface <code>lo0</code> o quadro começa
com 4 bytes do cabeçalho <i>Null/Loopback</i>; em seguida vêm o cabeçalho IPv4 (endereços <code>7f 00 00 0N</code>),
o UDP (portas <code>17 70</code> = 6000) e o texto UTF-8 da aplicação.</p>
<div class="avoid">{pre(tshark_detail("A_convergencia.pcapng", 'linkstate.tipo=="HELLO" && ip.src==127.0.0.4'))}</div>
<div class="avoid">{pre(tshark_detail("G_custo.pcapng", 'linkstate.tipo=="LSA" && linkstate.origem==127.0.0.1 && ip.src==127.0.0.1'))}</div>
<div class="avoid">{pre(tshark_detail("H_ttl.pcapng", 'linkstate.tipo=="DATA" && linkstate.ttl==2'))}</div>""")

    # ---------------- 9. cenários ----------------
    scen_intro = ("<p>Para cada cenário: comportamento esperado, resultado observado, LSAs relevantes (na captura), "
                  "alterações da LSDB e da tabela de roteamento e trechos de log. As tabelas destacadas são cópias "
                  "do que o roteador imprimiu no terminal no momento da mudança.</p>")

    # A
    a0 = SCEN["A"]["inicio"]
    dij = logs("A", ["R1"], include="DIJKSTRA_EXECUTADO")
    last_dij = dij.splitlines()[-1].split("│ ")[1][:12]
    acc_after = len([l for l in logs("A", ["R1"], include="LSA_ACEITO").splitlines()
                     if l.split("│ ")[1][:12] > last_dij])
    add(f"""<h2 class="scen">9. Cenários</h2>{scen_intro}
<h3>Cenário A – Convergência inicial da rede</h3>
<div class="box-exp"><b>Esperado</b>Ao iniciar, cada roteador gera o LSA local (sem enlaces) e roda o primeiro Dijkstra
com o que tem. Com os HELLOs bidirecionais as vizinhanças sobem, cada roteador gera novo LSA e sincroniza a LSDB com o
novo vizinho; em poucos segundos todos têm os 5 LSAs e as tabelas calculadas à mão. Renovações periódicas (10 s) não
disparam o Dijkstra.</div>
<div class="box-obs"><b>Observado</b>R1 a R5 foram iniciados com 0,3 s de intervalo. A rede convergiu em cerca de 1,3 s
(o último Dijkstra de R1 foi às {last_dij}). As tabelas finais coincidem com as esperadas (seção 7). Depois disso,
R1 aceitou mais {acc_after} LSAs de renovação sem nenhuma execução do Dijkstra.</div>
<p>Início de R1: LSA local vazio, vizinhanças, sincronização e primeiras rotas.</p>
{pre(logs("A", ["R1"], start=a0, limit=34))}
{wireshark_table("A_convergencia.pcapng", "ip.src==127.0.0.1 || ip.dst==127.0.0.1", limit=22,
                 caption="HELLO e LSAs trocados por R1 no início; note o HELLO imediato ao ativar a vizinhança e a sincronização (LSAs de outras origens enviados ao novo vizinho)")}
<p>Execuções do Dijkstra em R1 durante todo o cenário (o número de nós cresce conforme os LSAs chegam):</p>
{pre(dij)}
<div class="avoid"><p>LSDB e tabela de R1 após a convergência:</p>
{term_html(snap("A", "convergida_R1", "lsdb"))}</div>
{side_by_side(("R1", term_html(snap("A", "convergida_R1", "rotas"))),
              ("R2", term_html(snap("A", "convergida_R2", "rotas"))))}
{side_by_side(("R3", term_html(snap("A", "convergida_R3", "rotas"))),
              ("R4", term_html(snap("A", "convergida_R4", "rotas"))))}
{side_by_side(("R5", term_html(snap("A", "convergida_R5", "rotas"))), ("", ""))}""")

    # B
    t_add = event_time("B", "add 127.0.0.6")
    add(f"""<h3>Cenário B – Entrada de um novo roteador</h3>
<div class="box-exp"><b>Esperado</b>R6 (vizinhos R4 e R5) é ligado com a rede em funcionamento. Enquanto R4 e R5 não o
têm configurado, os HELLOs de R6 são descartados e o enlace não fica ativo. Depois do comando <code>add</code> em R4 e
R5 (que também grava o <code>roteadores.txt</code>), as vizinhanças sobem, R6 recebe toda a LSDB na sincronização e
todos os roteadores ganham uma rota [NOVA] para R6, sem reiniciar ninguém.</div>
<div class="box-obs"><b>Observado</b>R4 e R5 descartaram os HELLOs de R6 ("não é vizinho configurado"). Às {t_add}
foram executados <code>add 127.0.0.6 6</code> em R4 e <code>add 127.0.0.6 3</code> em R5; em milissegundos as
vizinhanças R4–R6 e R5–R6 ficaram ativas, R6 recebeu os LSAs de todas as origens e calculou a tabela completa. R1
ganhou a rota [NOVA] para R6 com custo 19 (via R5: 16+3), porque o LSA de R4 com o enlace R4–R6 ainda não tinha
chegado; 1 ms depois esse LSA chegou e a rota passou a 18 (R1→R2/R3→R4→R6 = 12+6).</div>
{pre(logs("B", ["R4", "R5", "R6"], include="HELLO_DESCARTADO|VIZINHO_|LSDB_SINCRONIZADA|ROTEADOR_INICIADO", limit=14))}
{wireshark_table("B_novo_roteador.pcapng", 'linkstate.tipo=="HELLO" && (ip.addr==127.0.0.6)', limit=12,
                 caption="antes do add, o HELLO de R4 para R6 não existia; depois dele, R4 envia HELLO a R6 e passa a listá-lo")}
{wireshark_table("B_novo_roteador.pcapng", f'linkstate.tipo=="LSA" && ip.dst==127.0.0.6', limit=12,
                 caption="sincronização: R4 e R5 enviam a R6 os LSAs de todas as origens assim que a vizinhança sobe")}
<p>LSAs aceitos por R6 na sincronização e primeira tabela:</p>
{pre(logs("B", ["R6"], include="LSA_ACEITO|DIJKSTRA", start=t_add, limit=12, strip_text=True))}
{side_by_side(("R1 – 1ª tabela após o add (rota nova, custo 19)", highlight_table(terminal_table("R1", t_add))),
              ("R1 – 1 ms depois (custo 18)", highlight_table(terminal_table("R1", t_add, nth=2))))}
{side_by_side(("R6 – LSDB após a sincronização", term_html(snap("B", "depois_add_lsdb_R6", "lsdb"))), ("", ""))}""")

    # C
    t_down = event_time("C", "down 127.0.0.4")
    t_up = event_time("C", "up 127.0.0.4")
    r4_down = logs("C", ["R4"], include="VIZINHO_INATIVO").splitlines()[0].split("│ ")[1][:12]
    c_delay = secs(r4_down) - secs(t_down)
    add(f"""<h3>Cenário C – Falha de um enlace</h3>
<div class="box-exp"><b>Esperado</b><code>down 127.0.0.4</code> em R2 desativa o enlace lógico R2–R4: R2 para de enviar
HELLO a R4, descarta HELLOs e LSAs vindos de R4, retira o enlace do seu LSA e recalcula na hora. R4 só percebe depois
de 15 s sem HELLO. Mesmo antes disso, os outros roteadores já deixam de usar a aresta, porque o LSA de R2 não reconhece
mais o enlace (verificação bidirecional). R1→R4 passa a ser só via R3 (custo 12). Com <code>up</code>, o enlace volta
apenas depois de um HELLO válido.</div>
<div class="box-obs"><b>Observado</b>Às {t_down}, R2 registrou ENLACE_DESATIVADO e VIZINHO_INATIVO e gerou novo LSA.
Os LSAs que chegavam por R4 foram descartados ("enlace com 127.0.0.4 desativado"). R4 marcou R2 como inativo às {r4_down},
{c_delay:.1f} s após o comando (15 s depois do último HELLO que R2 tinha enviado antes do <code>down</code>). A tabela de R1 trocou o próximo salto para R4/R5/R6 para R3 com os mesmos custos (o empate deixou de existir), e
R2 passou a alcançar R4 por R1 com custo 22 (10+5+7). Após <code>up</code> às {t_up}, a vizinhança voltou no
primeiro HELLO bidirecional.</div>
{pre(logs("C", ["R2", "R4"], include="ENLACE_|VIZINHO_|LSA_GERADO|LSA_DESCARTADO|HELLO_DESCARTADO", limit=22, strip_text=True))}
{wireshark_table("C_falha_enlace.pcapng", 'linkstate.tipo=="HELLO" && ip.addr==127.0.0.2 && ip.addr==127.0.0.4', limit=16,
                 caption="HELLOs entre R2 e R4: depois do down só R4→R2 continua (e é descartado por R2); após o up os dois sentidos voltam")}
{wireshark_table("C_falha_enlace.pcapng", 'linkstate.tipo=="LSA" && linkstate.origem==127.0.0.2 && ip.src==127.0.0.2', limit=6,
                 caption="LSA de R2 sem o enlace com 127.0.0.4 depois do down, e com ele de novo após o up")}
{side_by_side(("R1 – tabela impressa após o down", highlight_table(terminal_table("R1", t_down))),
              ("R2 – tabela impressa após o down", highlight_table(terminal_table("R2", t_down))))}
{side_by_side((f"R2 – vizinhos {after('C', 't03s_R2', t_down)} após o down", term_html(snap("C", "t03s_R2", "vizinhos"))),
              (f"R4 – vizinhos {after('C', 't19s_R4', t_down)} após o down", term_html(snap("C", "t19s_R4", "vizinhos"))))}
{side_by_side(("R1 – tabela após o up", term_html(snap("C", "depois_up_R1", "rotas"))),
              ("R2 – tabela após o up", term_html(snap("C", "depois_up_R2", "rotas"))))}
{side_by_side(("R1 – LSDB após a queda do enlace", term_html(snap("C", "t19s_lsdb_R1", "lsdb"))))}
<p>O LSA de R2 (SEQ 11) passou a anunciar só 127.0.0.1;10, e o de R4 (SEQ 13) não lista mais 127.0.0.2.</p>""")

    # D
    t_kill = event_time("D", "encerrado com Ctrl+C")
    add(f"""<h3>Cenário D – Falha de um roteador</h3>
<div class="box-exp"><b>Esperado</b>R4 é encerrado (Ctrl+C) sem aviso. Durante 15 s nada muda. Depois, R2, R3, R5 e R6
declaram R4 inativo e anunciam LSAs sem ele. Os enlaces de R4 deixam de ser usados assim que os vizinhos o retiram
dos seus LSAs, mesmo com o LSA de R4 ainda na LSDB. 30 s após a última versão aceita, o LSA de R4 expira e é removido;
o maior SEQ de R4 continua guardado. R4 some das tabelas.</div>
<div class="box-obs"><b>Observado</b>R4 foi encerrado às {t_kill}. Cerca de 12 s depois (15 s após o último HELLO de
R4) os vizinhos o declararam inativo e as rotas foram recalculadas: R1→R6 passou de 18 (caminho R1→R3→R4→R6) para 21 (R1→R3→R5→R6), com um passo intermediário de 19 quando R6 retirou o enlace com R4 antes dos demais, R1→R5 de 16 para 18 (via R3) e a rota para R4 foi removida. O LSA de R4 expirou em seguida, e a LSDB passou a mostrar
"Origens expiradas: 127.0.0.4 SEQ=…".</div>
{pre(logs("D", ["R1", "R2", "R3"], include="VIZINHO_INATIVO|LSA_EXPIRADO|ROTA_|LSDB_ATUALIZADA \\| 127.0.0.4", limit=26))}
{wireshark_table("D_falha_roteador.pcapng", 'ip.src==127.0.0.4 || (linkstate.tipo=="LSA" && linkstate.origem == ip.src && linkstate.origem in {127.0.0.2, 127.0.0.3, 127.0.0.5, 127.0.0.6} && frame.time_relative > 11.5 && frame.time_relative < 12.5)', limit=20,
                 caption="últimos LSAs repassados por R4 antes da falha e, cerca de 12 s depois, os primeiros LSAs gerados por R6, R3, R5 e R2 já sem o enlace com R4")}
{side_by_side((f"R1 – LSDB {after('D', 't05s_R1', t_kill)} após a falha", term_html(snap("D", "t05s_R1", "lsdb"))),
              (f"R1 – LSDB {after('D', 't34s_R1', t_kill)} após a falha", term_html(snap("D", "t34s_R1", "lsdb"))))}
{side_by_side((f"R1 – tabela {after('D', 't05s_R1', t_kill)} após (inalterada)", term_html(snap("D", "t05s_R1", "rotas"))),
              (f"R1 – tabela {after('D', 't19s_R1', t_kill)} após", term_html(snap("D", "t19s_R1", "rotas"))))}
{side_by_side((f"R2 – tabela {after('D', 't19s_R2', t_kill)} após", term_html(snap("D", "t19s_R2", "rotas"))), ("", ""))}""")

    # E
    t_start = event_time("E", "R4 (127.0.0.4) iniciado")
    add(f"""<h3>Cenário E – Recuperação após falha</h3>
<div class="box-exp"><b>Esperado</b>R4 é reiniciado na mesma pasta. Ele lê o <code>seq.txt</code> e continua a numeração
do valor gravado + 1, então os outros roteadores aceitam seus LSAs (eles ainda guardam o maior SEQ de R4). As
vizinhanças voltam no primeiro HELLO bidirecional, R4 recebe a LSDB pela sincronização e as rotas originais retornam.</div>
<div class="box-obs"><b>Observado</b>O <code>seq.txt</code> de R4 tinha {E(seq_r4)}; o primeiro LSA após o reinício saiu com
SEQ={int(seq_r4) + 1} e os seguintes foram aceitos pelos vizinhos (maior que o SEQ guardado). As quatro vizinhanças subiram
em menos de 1 s e as tabelas voltaram aos valores do cenário B (R1→R4 = 12, R1→R5 = 16, R1→R6 = 18).
Se o <code>seq.txt</code> fosse apagado, R4 recomeçaria em 1 e seus LSAs seriam descartados como antigos até que o
SEQ passasse do valor guardado pelos outros. Por isso o arquivo não deve ser apagado.</div>
{pre(logs("E", ["R4"], start=t_start, include="ROTEADOR_INICIADO|LSA_GERADO|VIZINHO_ATIVO|LSDB_SINCRONIZADA|DIJKSTRA", limit=16))}
{pre(logs("E", ["R1", "R3"], start=t_start, include="LSA_ACEITO \\| 127.0.0.4|VIZINHO_ATIVO|LSDB_SINCRONIZADA|ROTA_", limit=16))}
{wireshark_table("E_recuperacao.pcapng", 'linkstate.tipo=="LSA" && linkstate.origem==127.0.0.4', limit=10,
                 caption="os primeiros LSAs de R4 depois do reinício continuam a sequência gravada")}
{side_by_side(("R4 – LSDB após o reinício", term_html(snap("E", "depois_R4", "lsdb"))))}
{side_by_side(("R1 – tabela após a recuperação", term_html(snap("E", "depois_rotas_R1", "rotas"))),
              ("R2 – tabela após a recuperação", term_html(snap("E", "depois_rotas_R2", "rotas"))))}""")

    # F
    natural = {r: len(logs("A", [r], include="duplicado").splitlines()) for r in ("R1", "R2", "R3", "R4", "R5")}
    t_f = SCEN["F"]["inicio"]
    add(f"""<h3>Cenário F – Recebimento de LSAs antigos e duplicados</h3>
<div class="box-exp"><b>Esperado</b>Com o comando <code>replay</code>, R1 reenvia a R2 LSAs armazenados na sua LSDB:
o de R5 com o mesmo SEQ (duplicado), com SEQ−1 e com SEQ=1 (antigos) e o próprio LSA de R1 com o mesmo SEQ. R2 deve
descartar todos, sem flooding e sem renovar a validade.</div>
<div class="box-obs"><b>Observado</b>R2 registrou LSA_DESCARTADO com o motivo correto para os quatro e não houve
LSA_ENCAMINHADO nem LSA_ACEITO correspondente. O campo "Expira em" do LSA de R5 em R2 continuou diminuindo
(antes e depois do teste), provando que a validade não foi renovada. Duplicados também ocorrem naturalmente no
flooding (o mesmo LSA chega por dois caminhos): só no cenário A foram {", ".join(f"{r}: {n}" for r, n in natural.items())}
descartes de duplicados.</div>
{pre(logs("F", ["R1", "R2"], include="REENVIADO|LSA_DESCARTADO \\| 127.0.0.[15] \\| SEQ=(1|18|19) \\|.*via 127.0.0.1|LSA_ENCAMINHADO \\| 127.0.0.5 \\| SEQ=(1|18|19) ", start=t_f))}
{wireshark_table("F_lsa_antigo_duplicado.pcapng", 'linkstate.tipo=="LSA" && ip.src==127.0.0.1 && ip.dst==127.0.0.2', limit=10,
                 caption="LSAs enviados por R1 a R2. Os de origem 127.0.0.5 (SEQ 19, 18 e 1) são de teste. O LSA de R1 com SEQ 18 aparece duas vezes: a primeira é a renovação periódica normal (aceita por R2); a segunda, 1 s depois, é o replay com o mesmo SEQ (descartado como duplicado)")}
{side_by_side(("R2 – LSDB antes do teste", term_html(snap("F", "antes_R2", "lsdb"))),
              ("R2 – LSDB depois do teste", term_html(snap("F", "depois_R2", "lsdb"))))}
<p>Exemplos de descarte natural de duplicados durante o flooding (cenário A):</p>
{pre(logs("A", ["R3", "R4"], include="duplicado", limit=6))}""")

    # G
    t_g = event_time("G", "custo 127.0.0.2 1")
    add(f"""<h3>Cenário G – Alteração do custo de um enlace</h3>
<div class="box-exp"><b>Esperado</b><code>custo 127.0.0.2 1</code> em R1 muda só o sentido R1→R2 (10 → 1) e grava o
<code>roteadores.txt</code>. R1 gera um LSA na hora, todos recalculam, e as rotas de R1 que passam por R2 ficam mais
baratas: R2 = 1, R4 = 1+2 = 3, R5 = 3+4 = 7, R6 = 3+6 = 9, todas via R2 (os empates desaparecem). O sentido R2→R1
continua 10, então as rotas que chegam a R1 não mudam.</div>
<div class="box-obs"><b>Observado</b>Exatamente esses valores. A tabela de R1 foi impressa com as quatro linhas
[ALTERADA], e a tabela de R2 não mudou (custo assimétrico).</div>
{pre(logs("G", ["R1", "R2", "R5"], include="CUSTO_|LSA_GERADO \\| 127.0.0.1|LSA_ACEITO \\| 127.0.0.1|DIJKSTRA|ROTA_", limit=16))}
{wireshark_table("G_custo.pcapng", 'linkstate.tipo=="LSA" && linkstate.origem==127.0.0.1', limit=8,
                 caption="o novo LSA de R1 anuncia 127.0.0.2;1 e é repassado pelos vizinhos")}
{side_by_side(("R1 – tabela impressa após a mudança", highlight_table(terminal_table("R1", t_g))),
              ("R2 – tabela (inalterada)", term_html(snap("G", "depois_R2", "rotas"))))}
{side_by_side(("R2 – LSDB antes (fim do cenário F)", term_html(snap("F", "depois_R2", "lsdb"))),
              ("R2 – LSDB depois da mudança", term_html(snap("G", "depois_lsdb_R2", "lsdb"))))}
<p>Nos enlaces, só a entrada de 127.0.0.1 mudou: 127.0.0.2;10 → 127.0.0.2;1 (SEQ 18 → 19). As demais origens
apenas avançaram o SEQ pela renovação periódica, com os mesmos enlaces.</p>""")

    # H
    add(f"""<h3>Cenário H – Encaminhamento de DATA com TTL insuficiente</h3>
<div class="box-exp"><b>Esperado</b>Após o cenário G, R1→R5 segue R1→R2→R4→R5 (2 intermediários). A origem não
decrementa o TTL: <code>ttl=0</code> é descartado em R2, <code>ttl=1</code> chega a R4 com TTL 0 e é descartado lá,
<code>ttl=2</code> chega a R5 com TTL 0. Um envio com TTL padrão (16) chega com 14. Um destino sem rota é descartado
na origem.</div>
<div class="box-obs"><b>Observado</b>Os cinco envios se comportaram como esperado. A captura mostra o TTL do mesmo ID
diminuindo a cada salto (16 → 15 → 14), e os logs registram o motivo de cada descarte no roteador certo. O texto com
<code>;</code> foi entregue inteiro. A LSDB e as tabelas não mudam neste cenário; elas só são consultadas para encaminhar.</div>
{pre(logs("H", ["R1", "R2", "R4", "R5"], include="DATA_"))}
{wireshark_table("H_ttl.pcapng", 'linkstate.tipo=="DATA"', caption="todos os DATA: IPs e portas de cada salto e o TTL de cada datagrama")}
{side_by_side(("R1 – tabela usada", term_html(snap("H", "rotas_R1", "rotas"))),
              ("R2 – tabela", term_html(snap("H", "rotas_R2", "rotas"))),
              ("R4 – tabela", term_html(snap("H", "rotas_R4", "rotas"))))}""")

    # ---------------- 10. decisões ----------------
    add("""<h2 class="scen">10. Decisões de implementação e limitações</h2>
<p>Pontos em que a definição deixa a escolha ao grupo:</p>
<table class="grid"><tr><th>Ponto</th><th>Decisão</th></tr>
<tr><td>Limites dos campos</td><td>a definição fixa só o TTL (0 a 255) e que custos são inteiros positivos. O grupo
adotou custo de 1 a 65535 (16 bits, como a métrica de interface do OSPF) e SEQ de 1 a 2147483647 (maior inteiro de
32 bits com sinal, o <i>MaxSequenceNumber</i> do OSPF; a um LSA a cada 10 s levaria cerca de 680 anos para esgotar).
Assim qualquer grupo, em qualquer linguagem, representa os valores sem estouro. Valores fora desses limites tornam
a mensagem malformada.</td></tr>
<tr><td>Empate no Dijkstra</td><td>sorteio entre os próximos saltos de mesmo custo; se o próximo salto anterior continua
entre os melhores, ele é mantido, para a rota não aparecer como alterada sem motivo</td></tr>
<tr><td>HELLO</td><td>aceito só se o <code>IP_ORIGEM</code> for o IP de onde veio o datagrama</td></tr>
<tr><td>Flooding</td><td>o LSA é repassado como o datagrama original, sem alteração</td></tr>
<tr><td>Sincronização</td><td>ao formar a vizinhança, o roteador envia um HELLO imediato e só depois os LSAs (o próprio,
recém-gerado, e todos os outros válidos da LSDB). Como um LSA só é aceito de vizinho ativo, o HELLO imediato faz o
outro lado ativar a vizinhança antes de os LSAs chegarem (visto nos cenários A, B e E).</td></tr></table>
<p><b>Limitações.</b> (1) Os cenários deste relatório foram executados numa única máquina, com IPs de loopback; a
lógica e o formato na rede são os mesmos usados entre computadores, mas a demonstração em quatro ou mais
computadores e o teste de interoperabilidade com outros grupos são feitos no laboratório. (2) Como pede a
definição, não há confirmação nem retransmissão de LSAs: uma perda é corrigida pela renovação periódica de 10 s.
(3) Se o <code>seq.txt</code> for apagado, os LSAs do roteador serão descartados como antigos pelos que ainda
guardam o SEQ maior, até que a numeração o ultrapasse ou os outros reiniciem.</p>""")

    # ---------------- 11. execução ----------------
    add("""<h2>11. Como executar</h2>
<pre class="code"># um roteador por computador (pasta com roteadores.txt; seq.txt e router.log são criados nela)
python3 src/main.py --ip 192.168.1.1 --dir topologia/r1
tail -f topologia/r1/router.log            # log completo em outro terminal

# testes automatizados (parser, Dijkstra e cenários numa rede simulada)
python3 -m unittest discover -s tests -v

# reproduzir os cenários deste relatório numa máquina só (macOS) com captura
sudo bash scripts/preparar_mac.sh          # IPs 127.0.0.2-6 + permissão de captura
python3 scripts/cenarios.py                # ~3 min: capturas/*.pcapng e resultados/
python3 scripts/gerar_relatorio.py         # relatorio/relatorio.html e .pdf</pre>
<table class="grid"><tr><th>Comando</th><th>Função</th></tr>
<tr><td><code>lsdb</code> / <code>rotas</code> / <code>vizinhos</code></td><td>mostra a LSDB, a tabela de roteamento e o estado dos vizinhos</td></tr>
<tr><td><code>down &lt;ip&gt;</code> / <code>up &lt;ip&gt;</code></td><td>desativa / reativa o enlace lógico</td></tr>
<tr><td><code>custo &lt;ip&gt; &lt;n&gt;</code></td><td>altera o custo (gera LSA e grava o roteadores.txt)</td></tr>
<tr><td><code>add &lt;ip&gt; &lt;n&gt;</code> / <code>del &lt;ip&gt;</code></td><td>adiciona / remove vizinho (grava o roteadores.txt)</td></tr>
<tr><td><code>send &lt;ip&gt; [ttl=N] &lt;texto&gt;</code></td><td>envia DATA (TTL 0–255, padrão 16)</td></tr>
<tr><td><code>replay &lt;vizinho&gt; &lt;origem&gt; dup|old [seq]</code></td><td>reenvia ao vizinho o LSA armazenado de uma origem, duplicado ou antigo</td></tr>
<tr><td><code>log tudo|sem-hello|nada</code>, <code>help</code>, <code>sair</code></td><td>nível do log na tela, ajuda, encerrar</td></tr></table>""")

    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Relatório – Roteador Link State</title><style>{CSS}</style></head><body>{"".join(P)}</body></html>"""


def main():
    os.makedirs(OUT, exist_ok=True)
    doc = build()
    html_path = os.path.join(OUT, "relatorio.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(doc)
    print("HTML:", html_path)
    try:
        from weasyprint import HTML
    except Exception as e:
        print(f"WeasyPrint indisponível ({e}); PDF não gerado. Abra o HTML e imprima em PDF.")
        return
    pdf_path = os.path.join(OUT, "relatorio.pdf")
    HTML(html_path).write_pdf(pdf_path)
    print("PDF: ", pdf_path)


if __name__ == "__main__":
    sys.exit(main())
