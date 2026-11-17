-- Dissector Wireshark para o protocolo Link State do Trabalho Final (UDP 6000).
--
-- Mostra cada datagrama como HELLO, LSA ou DATA, com os campos separados.
-- Instalação (interface gráfica): copie este arquivo para
--   macOS/Linux: ~/.local/lib/wireshark/plugins/
--   Windows:     %APPDATA%\Wireshark\plugins\
-- e reabra o Wireshark (ou Analyze > Reload Lua Plugins).
-- Pelo tshark: tshark -X lua_script:wireshark/linkstate.lua -r captura.pcapng
--
-- Filtros úteis: linkstate.tipo == "HELLO" | "LSA" | "DATA"
--                linkstate.origem == 127.0.0.1    linkstate.seq    linkstate.ttl

local p = Proto("linkstate", "Link State TF Redes (HELLO/LSA/DATA)")

local f = {
  tipo     = ProtoField.string("linkstate.tipo", "Tipo"),
  origem   = ProtoField.ipv4("linkstate.origem", "IP_ORIGEM"),
  vizinho  = ProtoField.ipv4("linkstate.vizinho", "Vizinho configurado"),
  seq      = ProtoField.uint32("linkstate.seq", "SEQUENCIA"),
  enlace   = ProtoField.string("linkstate.enlace", "Enlace (vizinho;custo)"),
  enl_ip   = ProtoField.ipv4("linkstate.enlace.vizinho", "Vizinho"),
  enl_custo= ProtoField.uint32("linkstate.enlace.custo", "Custo"),
  destino  = ProtoField.ipv4("linkstate.destino", "IP_DESTINO"),
  id       = ProtoField.uint32("linkstate.id", "ID"),
  ttl      = ProtoField.uint8("linkstate.ttl", "TTL"),
  msg      = ProtoField.string("linkstate.mensagem", "MENSAGEM", base.UNICODE),
  nviz     = ProtoField.uint16("linkstate.qtd", "Quantidade de vizinhos/enlaces"),
  texto    = ProtoField.string("linkstate.texto", "Texto do datagrama", base.UNICODE),
}
p.fields = f

local e_malf = ProtoExpert.new("linkstate.malformada", "Mensagem malformada",
                               expert.group.MALFORMED, expert.severity.WARN)
local e_big  = ProtoExpert.new("linkstate.grande", "Datagrama acima de 1200 bytes",
                               expert.group.PROTOCOL, expert.severity.WARN)
p.experts = { e_malf, e_big }

local function ipv4(s)
  if not s then return nil end
  local a, b, c, d = s:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
  if not a then return nil end
  for _, x in ipairs({a, b, c, d}) do
    if tonumber(x) > 255 then return nil end
  end
  return Address.ip(s)
end

-- adiciona um campo IPv4 a partir de um trecho de texto (offset em bytes, 0-based)
local function add_ip(tree, field, buf, off, s)
  local addr = ipv4(s)
  if addr then
    return tree:add(field, buf(off, #s), addr)
  end
  return tree:add_proto_expert_info(e_malf, "IP inválido: " .. s)
end

local function dissect_hello(buf, tree, text)
  -- @IP_ORIGEM*VIZINHO1*VIZINHO2...
  local pos, parts = 1, {}
  local body = text:sub(2)
  for item, sep in (body .. "*"):gmatch("([^*]*)()%*") do
    parts[#parts + 1] = { s = item, off = pos }
    pos = pos + #item + 1
  end
  add_ip(tree, f.origem, buf, parts[1].off, parts[1].s)
  tree:add(f.nviz, #parts - 1):set_generated()
  for i = 2, #parts do
    add_ip(tree, f.vizinho, buf, parts[i].off, parts[i].s)
  end
  local viz = {}
  for i = 2, #parts do viz[#viz + 1] = parts[i].s end
  return string.format("HELLO  %s  vizinhos: %s", parts[1].s,
                       #viz > 0 and table.concat(viz, ", ") or "(nenhum)")
end

local function dissect_lsa(buf, tree, text)
  -- #IP_ORIGEM;SEQ*VIZINHO;CUSTO*VIZINHO;CUSTO
  local pos, parts = 1, {}
  for item in (text:sub(2) .. "*"):gmatch("([^*]*)%*") do
    parts[#parts + 1] = { s = item, off = pos }
    pos = pos + #item + 1
  end
  local o, sq = parts[1].s:match("^([^;]+);(%d+)$")
  if not o then
    tree:add_proto_expert_info(e_malf, "cabeçalho do LSA inválido")
    return "LSA (malformado)"
  end
  add_ip(tree, f.origem, buf, parts[1].off, o)
  tree:add(f.seq, buf(parts[1].off + #o + 1, #sq), tonumber(sq))
  tree:add(f.nviz, #parts - 1):set_generated()
  local links = {}
  for i = 2, #parts do
    local v, c = parts[i].s:match("^([^;]+);(%d+)$")
    local sub = tree:add(f.enlace, buf(parts[i].off, #parts[i].s), parts[i].s)
    if v then
      add_ip(sub, f.enl_ip, buf, parts[i].off, v)
      sub:add(f.enl_custo, buf(parts[i].off + #v + 1, #c), tonumber(c))
      links[#links + 1] = v .. "=" .. c
    else
      sub:add_proto_expert_info(e_malf, "enlace inválido")
    end
  end
  return string.format("LSA    origem %s  SEQ=%s  enlaces: %s", o, sq,
                       #links > 0 and table.concat(links, " ") or "(nenhum)")
end

local function dissect_data(buf, tree, text)
  -- !IP_ORIGEM;IP_DESTINO;ID;TTL;MENSAGEM   (a mensagem pode conter ';')
  local o, d, id, ttl, rest = text:match("^!([^;]*);([^;]*);([^;]*);([^;]*);(.*)$")
  if not o then
    tree:add_proto_expert_info(e_malf, "DATA com menos de 5 campos")
    return "DATA (malformado)"
  end
  local off = 1
  add_ip(tree, f.origem, buf, off, o);   off = off + #o + 1
  add_ip(tree, f.destino, buf, off, d);  off = off + #d + 1
  tree:add(f.id, buf(off, #id), tonumber(id) or 0);  off = off + #id + 1
  tree:add(f.ttl, buf(off, #ttl), tonumber(ttl) or 0); off = off + #ttl + 1
  if #rest > 0 then
    tree:add(f.msg, buf(off, #rest), rest)
  end
  return string.format("DATA   %s -> %s  ID=%s  TTL=%s  \"%s\"", o, d, id, ttl, rest)
end

function p.dissector(buf, pinfo, tree)
  local len = buf:len()
  if len == 0 then return 0 end
  local text = buf():raw()
  local first = text:sub(1, 1)
  local kinds = { ["@"] = "HELLO", ["#"] = "LSA", ["!"] = "DATA" }
  local kind = kinds[first]

  pinfo.cols.protocol = kind and ("LS-" .. kind) or "LINKSTATE"
  local t = tree:add(p, buf(), "Link State TF Redes" .. (kind and (" – " .. kind) or ""))
  t:add(f.tipo, buf(0, 1), kind or "DESCONHECIDO")
  t:add(f.texto, buf(), text)
  if len > 1200 then t:add_proto_expert_info(e_big) end

  local info
  if kind == "HELLO" then
    info = dissect_hello(buf, t, text)
  elseif kind == "LSA" then
    info = dissect_lsa(buf, t, text)
  elseif kind == "DATA" then
    info = dissect_data(buf, t, text)
  else
    t:add_proto_expert_info(e_malf, "primeiro caractere não é @, # ou !")
    info = "Mensagem desconhecida/malformada"
  end
  pinfo.cols.info = info
  return len
end

DissectorTable.get("udp.port"):add(6000, p)
