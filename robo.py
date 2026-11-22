#!/usr/bin/env python3
"""
Robô da Agenda PUMP THE JAM — festas flashback e dance music (SP capital + interior).

Fontes automáticas: Sympla, Eventbrite, Shotgun (dados JSON-LD das páginas de busca).
Fonte manual: extras.csv (Toco, kaikans, Energia 97, shows como Double You...).
Saída: docs/index.html (calendário visual), docs/agenda.json, docs/agenda.ics
"""
import csv, json, re, time, html, datetime as dt
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse, urlunparse, parse_qsl
import requests
from bs4 import BeautifulSoup

TERMOS = ["flashback", "anos 90", "anos 80", "anos 2000", "festa ploc", "eurodance",
          "poperô", "dance 90", "toco", "kaikan", "energia 97", "double you",
          "remember", "nostalgia", "eletrohits"]
CIDADES = {  # sympla : eventbrite
    "sao-paulo-sp": "sao-paulo", "campinas-sp": "campinas", "santos-sp": "santos",
    "sao-jose-dos-campos-sp": "sao-jose-dos-campos", "ribeirao-preto-sp": "ribeirao-preto",
    "sorocaba-sp": "sorocaba", "jundiai-sp": "jundiai", "piracicaba-sp": "piracicaba",
    "bauru-sp": "bauru", "sao-jose-do-rio-preto-sp": "sao-jose-do-rio-preto",
    "sao-carlos-sp": "sao-carlos", "santo-andre-sp": "santo-andre",
    "sao-bernardo-do-campo-sp": "sao-bernardo-do-campo", "guarulhos-sp": "guarulhos",
}
TEMA = re.compile(r"flash ?back|anos ?(70|80|90|2000)|\b(80|90|00)'?s\b|ploc|eurodance|poper[ôo]|"
                  r"dance music|\btoco\b|kaikan|energia ?97|double you|remember|nostalgi|"
                  r"eletro ?hits|new wave|disco|cringe|passinho|freestyle", re.I)
FORA = re.compile(r"pagode|sertanej|gospel|infantil|curso|workshop|palestra", re.I)
UA = {"User-Agent": "Mozilla/5.0 (compatible; PUMPTHEJAM-agenda/1.0; pumpthejamwear@gmail.com)"}
UTM = {"utm_source": "pumpthejam", "utm_medium": "agenda", "utm_campaign": "agenda_flashback"}
OUT = Path("docs"); OUT.mkdir(exist_ok=True)


def com_utm(url, content):
    if not url: return ""
    p = urlparse(url); q = dict(parse_qsl(p.query)); q.update(UTM); q["utm_content"] = content
    return urlunparse(p._replace(query=urlencode(q)))


def jsonld(html_txt):
    out = []
    for s in BeautifulSoup(html_txt, "html.parser").find_all("script", type="application/ld+json"):
        try: data = json.loads(s.string or "")
        except Exception: continue
        pilha = data if isinstance(data, list) else [data]
        while pilha:
            d = pilha.pop()
            if not isinstance(d, dict): continue
            t = d.get("@type", ""); t = t if isinstance(t, str) else " ".join(t)
            if "Event" in t: out.append(d)
            for k in ("itemListElement", "@graph", "item"):
                v = d.get(k)
                if isinstance(v, list): pilha += v
                elif isinstance(v, dict): pilha.append(v)
    return out


def norm(ev, fonte):
    loc = ev.get("location") or {}
    if isinstance(loc, list): loc = loc[0] if loc else {}
    end = loc.get("address") or {}
    img = ev.get("image") or ""
    if isinstance(img, list): img = img[0] if img else ""
    if isinstance(img, dict): img = img.get("url", "")
    return {"nome": (ev.get("name") or "").strip(), "inicio": ev.get("startDate", ""),
            "local": loc.get("name", ""),
            "cidade": end.get("addressLocality", "") if isinstance(end, dict) else str(end),
            "url": ev.get("url", ""), "imagem": img, "fonte": fonte, "tipo": "festa"}


def get(url, fonte):
    try:
        r = requests.get(url, headers=UA, timeout=25); r.raise_for_status()
        return [norm(e, fonte) for e in jsonld(r.text)]
    except Exception as e:
        print(f"  ! {fonte} {url[:70]}: {e}"); return []


def extras():
    evs = []
    f = Path("extras.csv")
    if not f.exists(): return evs
    linhas = [l for l in f.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    for r in csv.DictReader(linhas):
        hora = (r.get("hora") or "22:00").strip()
        evs.append({"nome": r["nome"], "inicio": f'{r["data"]}T{hora}', "local": r.get("local", ""),
                    "cidade": r.get("cidade", ""), "url": r.get("url", ""), "imagem": r.get("imagem", ""),
                    "fonte": "manual", "tipo": r.get("tipo") or "festa", "manual": True})
    return evs


def coleta():
    evs = []
    for sym, eb in CIDADES.items():
        for t in TERMOS:
            print(f"- {sym} · {t}")
            evs += get(f"https://www.sympla.com.br/eventos/{sym}?s={quote(t)}", "sympla")
            evs += get(f"https://www.eventbrite.com.br/d/brazil--{eb}/{quote(t.replace(' ', '-'))}/", "eventbrite")
            time.sleep(1.2)
    for t in TERMOS:
        evs += get(f"https://shotgun.live/pt-br/cities/sao-paulo?search={quote(t)}", "shotgun")
    hoje = dt.date.today().isoformat()
    vistos, final = set(), []
    for e in evs + extras():
        k = (re.sub(r"\W", "", e["nome"].lower())[:40], e["inicio"][:10])
        txt = e["nome"] + " " + e["local"]
        ok = e.get("manual") or (TEMA.search(txt) and not FORA.search(txt))
        if e["nome"] and e["inicio"][:10] >= hoje and k not in vistos and ok:
            vistos.add(k); final.append(e)
    final.sort(key=lambda e: e["inicio"])
    for e in final:
        e["link"] = com_utm(e["url"], re.sub(r"[^a-z0-9]+", "-", e["nome"].lower())[:40])
    return final


def ics(evs):
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//PUMP THE JAM//Agenda//PT",
         "X-WR-CALNAME:Agenda Flashback PUMP THE JAM", "X-WR-TIMEZONE:America/Sao_Paulo"]
    for i, e in enumerate(evs):
        d = re.sub(r"[-:]", "", e["inicio"])[:13].ljust(13, "0")
        L += ["BEGIN:VEVENT", f"UID:ptj-{i}-{d}@pumpthejam.com.br", f"DTSTART;TZID=America/Sao_Paulo:{d}00",
              f"SUMMARY:{e['nome']}", f"LOCATION:{e['local']} - {e['cidade']}", f"URL:{e['link']}", "END:VEVENT"]
    L.append("END:VCALENDAR")
    (OUT / "agenda.ics").write_text("\r\n".join(L), encoding="utf-8")


def pagina(evs):
    tpl = Path("template.html").read_text(encoding="utf-8")
    dados = json.dumps(evs, ensure_ascii=False).replace("</", "<\\/")
    agora = dt.datetime.now().strftime("%d/%m/%Y %H:%M")
    (OUT / "index.html").write_text(tpl.replace("__DADOS__", dados).replace("__ATUALIZADO__", agora),
                                    encoding="utf-8")


if __name__ == "__main__":
    evs = coleta()
    (OUT / "agenda.json").write_text(json.dumps(evs, ensure_ascii=False, indent=2), encoding="utf-8")
    ics(evs); pagina(evs)
    print(f"\n{len(evs)} eventos → docs/index.html, agenda.json, agenda.ics")
