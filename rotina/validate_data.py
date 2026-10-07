#!/usr/bin/env python3
"""Valida um data-<lancamento>.json contra o contrato fortraffic-dashboard/1.

Uso:   python3 validate_data.py data-leads.json [outro.json ...]
Saída: lista de ERROS (impedem o dashboard de renderizar certo) e AVISOS (renderiza, mas algo está estranho).
Código de saída 1 se houver qualquer ERRO. Também importável: validar(dict) -> (erros, avisos).
"""
import json, re, sys

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PAGINAS = {"captacao", "meta", "metricas", "pais", "general", "pesquisa", "scoring"}
META_OBRIG = ["cliente", "evento", "atualizado_em", "moeda"]


def _datas(rows, nome, erros, avisos):
    ruins = [r.get("d") for r in rows if not (isinstance(r.get("d"), str) and ISO.match(r["d"]))]
    if ruins:
        erros.append(f"{nome}: {len(ruins)} linha(s) com data fora de yyyy-mm-dd (ex.: {ruins[0]!r}). Nunca fatie string de data; converta com datetime.")
    return max((r["d"] for r in rows if isinstance(r.get("d"), str) and ISO.match(r["d"])), default=None)


def _nums(rows, campos, nome, erros):
    for c in campos:
        for r in rows[:2000]:
            if c in r and r[c] is not None and not isinstance(r[c], (int, float)):
                erros.append(f"{nome}: campo '{c}' precisa ser número (achei {type(r[c]).__name__}: {r[c]!r})")
                break


def validar(d):
    erros, avisos = [], []
    if d.get("schema") != "fortraffic-dashboard/1":
        avisos.append("schema ausente ou diferente de 'fortraffic-dashboard/1'")
    meta, cfg = d.get("meta") or {}, d.get("config") or {}
    for k in META_OBRIG:
        if not meta.get(k):
            erros.append(f"meta.{k} é obrigatório")
    if meta.get("cor") and not re.match(r"^#[0-9a-fA-F]{6}$", meta["cor"]):
        erros.append("meta.cor precisa ser hex de 6 dígitos (ex.: #252F26)")
    if meta.get("data_ate") and not ISO.match(meta["data_ate"]):
        erros.append("meta.data_ate precisa ser yyyy-mm-dd (último dia FECHADO, normalmente ontem)")
    modo = cfg.get("modo")
    if modo not in ("leads", "vendas"):
        erros.append("config.modo precisa ser 'leads' ou 'vendas'")
    pgs = cfg.get("paginas")
    if pgs is not None:
        for p in pgs:
            if p not in PAGINAS:
                erros.append(f"config.paginas contém página desconhecida: {p!r} (válidas: {sorted(PAGINAS)})")
    else:
        avisos.append("config.paginas ausente: o dashboard liga páginas por padrão do modo")

    maxd = []
    anuncios = d.get("anuncios") or []
    if not anuncios:
        erros.append("anuncios vazio: sem isso não há Captação nem Meta Ads")
    else:
        maxd.append(_datas(anuncios, "anuncios", erros, avisos))
        _nums(anuncios, ["sp", "imp", "lc", "pv", "ic", "pur"], "anuncios", erros)
        faltam = {c for r in anuncios[:500] for c in ("c", "a", "an") if not r.get(c)}
        if faltam:
            avisos.append(f"anuncios: linhas sem {sorted(faltam)} (campanha/conjunto/anúncio vazios quebram as tabelas)")
        if sum(r.get("sp", 0) for r in anuncios) == 0:
            avisos.append("anuncios: investimento total = 0")
    if modo == "leads":
        leads = d.get("leads") or []
        if not leads:
            erros.append("modo leads exige o bloco 'leads' (linhas agregadas com campo n)")
        else:
            maxd.append(_datas(leads, "leads", erros, avisos))
            _nums(leads, ["n"], "leads", erros)
            if any(r.get("t") not in ("HOT", "COLD", "OUTRO") for r in leads):
                erros.append("leads.t precisa ser HOT, COLD ou OUTRO")
    if modo == "vendas":
        vendas = d.get("vendas") or []
        if not vendas:
            erros.append("modo vendas exige o bloco 'vendas'")
        else:
            maxd.append(_datas(vendas, "vendas", erros, avisos))
            _nums(vendas, ["v"], "vendas", erros)
            if any(r.get("org") not in ("Pago", "Orgânico") for r in vendas):
                erros.append("vendas.org precisa ser 'Pago' ou 'Orgânico'")
            nomes = {p["nome"] for p in d.get("produtos", [])}
            sem = {r["p"] for r in vendas} - nomes
            if sem:
                avisos.append(f"vendas com produto fora de 'produtos' (tratado como não-upsell): {sorted(sem)[:3]}")
        if cfg.get("compras_fonte") not in (None, "pixel", "vendas_pagas"):
            erros.append("config.compras_fonte: 'pixel' ou 'vendas_pagas'")
    for k in ("genero", "idade", "posicao", "pais"):
        rows = (d.get("segmentos") or {}).get(k) or []
        if rows:
            _datas(rows, f"segmentos.{k}", erros, avisos)
            _nums(rows, ["sp", "res"], f"segmentos.{k}", erros)
    if "pais" in (pgs or []) and not (d.get("segmentos") or {}).get("pais"):
        avisos.append("página 'pais' ligada mas segmentos.pais está vazio")
    if "scoring" in (pgs or []):
        sc = d.get("lead_scoring")
        if not sc:
            erros.append("página 'scoring' ligada mas lead_scoring ausente")
        else:
            for k in ("totais", "grupos"):
                if k not in sc:
                    erros.append(f"lead_scoring.{k} é obrigatório")
            if not sc.get("explicacao"):
                avisos.append("lead_scoring.explicacao ausente: o card 'Como classificamos os leads' não aparece")
            for g in sc.get("grupos", []):
                if g.get("total") != g.get("ideal", 0) + g.get("bom", 0) + g.get("descarte", 0):
                    erros.append("lead_scoring.grupos: total != ideal+bom+descarte")
                    break
    if "pesquisa" in (pgs or []):
        if not (d.get("pesquisa") or {}).get("rows"):
            erros.append("página 'pesquisa' ligada mas pesquisa.rows ausente")
        else:
            bad = [k for r in d["pesquisa"]["rows"][:50] for k in r if re.search(r"e-?mail|whats|tel[eé]fone|phone|cpf", k, re.I)]
            if bad:
                erros.append(f"pesquisa.rows contém coluna de dado pessoal ({bad[0]!r}). O JSON é público no GitHub Pages: remova.")
    # nenhum e-mail pode vazar em nenhum bloco
    txt = json.dumps(d, ensure_ascii=False)
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", txt):
        erros.append("o JSON contém algo com cara de e-mail. O arquivo é público: remova antes de publicar.")
    ult = max([m for m in maxd if m], default=None)
    if ult and meta.get("data_ate") and ult > meta["data_ate"]:
        avisos.append(f"há dados posteriores a meta.data_ate ({ult} > {meta['data_ate']}); o filtro 'Ontem' usa data_ate")
    if not meta.get("data_ate"):
        avisos.append("meta.data_ate ausente: o dashboard usará a maior data encontrada")
    if len(txt.encode()) > 3_000_000:
        avisos.append(f"JSON com {len(txt)//1024} KB: acima de 3 MB o carregamento no celular fica lento (agregue por dia/campanha/anúncio)")
    return erros, avisos


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    falhou = False
    for f in sys.argv[1:]:
        e, a = validar(json.load(open(f, encoding="utf-8")))
        print(f"== {f}: {len(e)} erro(s), {len(a)} aviso(s)")
        for x in e:
            print("  ERRO ", x)
        for x in a:
            print("  aviso", x)
        falhou = falhou or bool(e)
    sys.exit(1 if falhou else 0)
