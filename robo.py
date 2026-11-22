#!/usr/bin/env python3
"""
Robô da Agenda PUMP THE JAM — festas flashback e dance music (SP capital + interior).

Fontes automáticas: Sympla, Eventbrite, Shotgun (dados JSON-LD das páginas de busca).
Fonte manual: extras.csv (Toco, kaikans, Energia 97, shows como Double You...).
Saída: docs/index.html (calendário visual), docs/agenda.json, docs/agenda.ics
"""
import csv, json, os, re, time, html, unicodedata, datetime as dt
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse, urlunparse, parse_qsl
import requests
from bs4 import BeautifulSoup

TERMOS = ["flashback", "anos 90", "anos 80", "anos 2000", "eurodance", "eletrohits", "remember", "kaikan", "double you", "energia 97"]
CIDADES = {  # sympla : eventbrite
    "sao-paulo-sp": "sao-paulo", "campinas-sp": "campinas", "santos-sp": "santos",
    "sao-jose-dos-campos-sp": "sao-jose-dos-campos", "ribeirao-preto-sp": "ribeirao-preto",
    "sorocaba-sp": "sorocaba", "jundiai-sp": "jundiai", "piracicaba-sp": "piracicaba",
    "bauru-sp": "bauru", "sao-jose-do-rio-preto-sp": "sao-jose-do-rio-preto",
    "sao-carlos-sp": "sao-carlos", "santo-andre-sp": "santo-andre",
    "sao-bernardo-do-campo-sp": "sao-bernardo-do-campo", "guarulhos-sp": "guarulhos",
}
TEMA = re.compile(r"cl[uo]be dos 30|kombuca|flash ?back|anos ?(70|80|90|2000)|\b(80|90|00)'?s\b|ploc|eurodance|poper[ôo]|"
                  r"dance music|\btoco\b|kaikan|energia ?97|double you|remember|nostalgi|"
                  r"eletro ?hits|new wave|disco|cringe|passinho|freestyle", re.I)
FORA = re.compile(r"pagode|sertanej|gospel|infantil|curso|workshop|palestra", re.I)
UA = {"User-Agent": "Mozilla/5.0 (compatible; PUMPTHEJAM-agenda/1.0; pumpthejamwear@gmail.com)"}
UTM = {"utm_source": "pumpthejam", "utm_medium": "agenda", "utm_campaign": "agenda_flashback"}
OUT = Path("docs"); OUT.mkdir(exist_ok=True)


def slug(txt, n=40):
    t = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:n]


def com_utm(url, content, term=""):
    if not url: return ""
    p = urlparse(url); q = dict(parse_qsl(p.query)); q.update(UTM); q["utm_content"] = content
    if term: q["utm_term"] = term
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


MES = {"jan":1,"fev":2,"mar":3,"abr":4,"mai":5,"jun":6,"jul":7,"ago":8,"set":9,"out":10,"nov":11,"dez":12}


def data_sympla(txt):
    """'Sexta, 04 de Dez às 18:00' -> '2026-12-04T18:00'"""
    m = re.search(r"(\d{1,2}) de (\w{3})\w*(?:.*?(\d{1,2}:\d{2}))?", txt, re.I)
    if not m: return ""
    d, mes = int(m.group(1)), MES.get(m.group(2).lower()[:3])
    if not mes: return ""
    hoje = dt.date.today(); ano = hoje.year + (1 if mes < hoje.month else 0)
    return f"{ano}-{mes:02d}-{d:02d}T{m.group(3) or '22:00'}"


def sympla(page, cidade, termo):
    """Sympla monta a lista no navegador: usa Chromium (Playwright) e lê os cards."""
    url = f"https://www.sympla.com.br/eventos/{cidade}?s={quote(termo)}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_selector('a[href*="/evento/"]', timeout=12000)
    except Exception:
        return []
    cards = page.eval_on_selector_all('a[href*="/evento/"]', """els => els.map(a => ({
        href: a.href.split('?')[0], txt: a.innerText,
        img: (a.querySelector('img')||{}).src || ''}))""")
    out = []
    for c in cards:
        linhas = [l.strip() for l in c["txt"].split("\n") if l.strip()]
        if len(linhas) < 2: continue
        quando = next((l for l in linhas if re.search(r"\d{1,2} de \w{3}", l)), "")
        onde = next((l for l in linhas if re.search(r", [A-Z]{2}$", l)), "")
        if onde and not onde.endswith("SP"): continue
        out.append({"nome": linhas[0], "inicio": data_sympla(quando), "local": "",
                    "cidade": onde.split(",")[0], "url": c["href"], "imagem": c["img"],
                    "fonte": "sympla", "tipo": "show" if re.search(r"show|turn[êe]|tour", linhas[0], re.I) else "festa"})
    return out


def coleta():
    evs = []
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        nav = p.chromium.launch()
        page = nav.new_page(user_agent=UA["User-Agent"], locale="pt-BR")
        for sym in CIDADES:
            for t in TERMOS:
                achou = sympla(page, sym, t)
                print(f"- sympla {sym} · {t}: {len(achou)}")
                evs += achou
                time.sleep(1)
        nav.close()
    for sym, eb in CIDADES.items():
        for t in TERMOS[:6]:
            evs += get(f"https://www.eventbrite.com.br/d/brazil--{eb}/{quote(t.replace(' ', '-'))}/", "eventbrite")
            time.sleep(1)
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
        e["link"] = com_utm(e["url"], slug(e["nome"]), slug(e.get("cidade", "")))
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
    (OUT / "index.html").write_text((tpl.replace("__DADOS__", dados).replace("__ATUALIZADO__", agora)
                                     .replace("__GA4_ID__", os.environ.get("GA4_ID", ""))
                                     .replace("__META_PIXEL_ID__", os.environ.get("META_PIXEL_ID", ""))),
                                    encoding="utf-8")


if __name__ == "__main__":
    evs = coleta()
    (OUT / "agenda.json").write_text(json.dumps(evs, ensure_ascii=False, indent=2), encoding="utf-8")
    ics(evs); pagina(evs)
    print(f"\n{len(evs)} eventos → docs/index.html, agenda.json, agenda.ics")
