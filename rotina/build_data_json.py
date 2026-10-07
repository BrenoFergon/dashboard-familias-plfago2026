#!/usr/bin/env python3
"""Monta o data-<lancamento>.json no contrato fortraffic-dashboard/1 a partir de DataFrames.

Separação de responsabilidades (por isso este arquivo é pequeno e reaproveitável):
  - A rotina (ou o gestor) lê a planilha e entrega DataFrames com NOMES NORMALIZADOS (abaixo).
  - Este módulo cuida do FORMATO: datas ISO, números, agregação, estrutura do contrato.
O mapeamento "coluna X da planilha do cliente -> nome normalizado" fica no prompt da rotina,
porque muda de cliente para cliente. Este módulo não muda.

Colunas normalizadas esperadas
  gerenciador : date, campaign, adset, ad, spend, impressions, link_clicks, page_view, init_checkout, purchase, status(opc)
  leads       : date, campaign(utm_term), adset(utm_medium), ad(utm_content), canal(utm_source), tipo(opc: HOT/COLD), pais(opc)
  vendas      : date, produto, valor, origem(Pago/Orgânico), oferta, utm_source, utm_medium, utm_campaign, utm_content, utm_term, pais
  segmento    : date, campaign, chave, spend, resultado   (uma tabela por dimensão: genero, idade, posicao)
  segmento_pais: date, campaign, adset(opc), pais, spend, resultado

Uso mínimo:
    import build_data_json as B
    d = B.montar(meta=..., config=..., gerenciador=df_g, leads=df_l)   # modo leads
    B.salvar(d, "docs/data-meu-lancamento.json")
"""
import json, re
import pandas as pd

HOT = re.compile(r"(^|[^a-z])(hot|quente|caliente)([^a-z]|$)", re.I)
COLD = re.compile(r"(^|[^a-z])(cold|frio|fr[ií]o)([^a-z]|$)", re.I)


def iso(v):
    """Qualquer coisa que pareça data -> 'yyyy-mm-dd' (ou None). Aceita datetime, 'dd/mm/aaaa', 'aaaa-mm-dd'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (pd.Timestamp,)) or hasattr(v, "strftime"):
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    s = str(v).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return None
    ts = pd.to_datetime(s, dayfirst="/" in s, errors="coerce")
    return None if pd.isna(ts) else ts.strftime("%Y-%m-%d")


def numero(s):
    """Série -> float. Entende '1.234,56' (BR) e '1234.56' (US)."""
    if pd.api.types.is_numeric_dtype(s):
        return s.fillna(0).astype(float)
    t = s.astype(str).str.strip().str.replace(r"[^\d,.\-]", "", regex=True)
    br = t.str.contains(r"\d,\d", regex=True).any()
    if br:
        t = t.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(t, errors="coerce").fillna(0)


def _txt(s):
    return s.fillna("").astype(str).str.strip().replace({"nan": "", "None": ""})


def _com_data(df):
    """Mantém só linhas com data válida (planilhas têm milhares de linhas vazias com formatação residual)."""
    df = df.copy()
    df["d"] = df["date"].map(iso)
    return df[df["d"].notna()]


def tipo_de(*textos):
    for t in textos:
        t = t or ""
        if HOT.search(t):
            return "HOT"
        if COLD.search(t):
            return "COLD"
    return "OUTRO"


def anuncios(df):
    df = _com_data(df)
    for c in ("spend", "impressions", "link_clicks", "page_view", "init_checkout", "purchase"):
        df[c] = numero(df[c]) if c in df.columns else 0.0
    for c in ("campaign", "adset", "ad"):
        df[c] = _txt(df[c])
    df["status"] = _txt(df["status"]) if "status" in df.columns else ""
    g = df.groupby(["d", "campaign", "adset", "ad"], as_index=False).agg(
        sp=("spend", "sum"), imp=("impressions", "sum"), lc=("link_clicks", "sum"), pv=("page_view", "sum"),
        ic=("init_checkout", "sum"), pur=("purchase", "sum"), st=("status", "last"))
    g = g.rename(columns={"campaign": "c", "adset": "a", "ad": "an"})
    g["sp"] = g["sp"].round(2)
    for c in ("imp", "lc", "pv", "ic", "pur"):
        g[c] = g[c].round().astype(int)
    return g.sort_values(["d", "c", "a", "an"]).to_dict("records")


def leads(df):
    df = _com_data(df)
    for c in ("campaign", "adset", "ad", "canal"):
        df[c] = _txt(df[c]) if c in df.columns else ""
    df["canal"] = df["canal"].str.lower()
    df["pais"] = _txt(df["pais"]).str.upper() if "pais" in df.columns else ""
    if "tipo" in df.columns:
        df["t"] = _txt(df["tipo"]).str.upper().where(lambda s: s.isin(["HOT", "COLD"]), "OUTRO")
    else:
        df["t"] = [tipo_de(a, c) for a, c in zip(df["adset"], df["campaign"])]
    g = df.groupby(["d", "t", "campaign", "adset", "ad", "canal", "pais"], as_index=False).size()
    g = g.rename(columns={"campaign": "c", "adset": "a", "ad": "an", "canal": "ch", "pais": "ps", "size": "n"})
    return g.sort_values(["d", "t", "c"]).to_dict("records")


def vendas(df):
    df = _com_data(df)
    out = []
    for r in df.to_dict("records"):
        org = str(r.get("origem") or "").strip()
        out.append(dict(
            d=r["d"], p=str(r.get("produto") or ""), v=float(numero(pd.Series([r.get("valor")])).iloc[0]),
            org="Pago" if org.lower().startswith("pag") else "Orgânico",
            of=str(r.get("oferta") or "").strip().lower().replace("nan", ""),
            us=str(r.get("utm_source") or "").replace("nan", ""), um=str(r.get("utm_medium") or "").replace("nan", ""),
            uc=str(r.get("utm_campaign") or "").replace("nan", ""), uco=str(r.get("utm_content") or "").replace("nan", ""),
            ut=str(r.get("utm_term") or "").replace("nan", ""), ps=str(r.get("pais") or "").upper().replace("NAN", "")))
    return out


def segmento(df):
    df = _com_data(df)
    df["spend"] = numero(df["spend"])
    df["resultado"] = numero(df["resultado"]) if "resultado" in df.columns else 0
    df["campaign"] = _txt(df["campaign"])
    df["chave"] = _txt(df["chave"])
    g = df.groupby(["d", "campaign", "chave"], as_index=False).agg(sp=("spend", "sum"), res=("resultado", "sum"))
    g = g.rename(columns={"campaign": "c", "chave": "k"})
    g["sp"] = g["sp"].round(2)
    g["res"] = g["res"].round().astype(int)
    return g.to_dict("records")


def segmento_pais(df):
    df = _com_data(df)
    df["spend"] = numero(df["spend"])
    df["resultado"] = numero(df["resultado"]) if "resultado" in df.columns else 0
    df["campaign"] = _txt(df["campaign"])
    df["adset"] = _txt(df["adset"]) if "adset" in df.columns else ""
    df["ps"] = _txt(df["pais"]).str.upper()
    g = df.groupby(["d", "campaign", "adset", "ps"], as_index=False).agg(sp=("spend", "sum"), res=("resultado", "sum"))
    g = g.rename(columns={"campaign": "c", "adset": "a"})
    g["sp"] = g["sp"].round(2)
    g["res"] = g["res"].round().astype(int)
    return g.to_dict("records")


def montar(meta, config, gerenciador, leads_df=None, vendas_df=None, produtos=None, segmentos=None,
           criativos=None, pesquisa=None, lead_scoring=None, leitura=None):
    """meta: cliente, letra, cor, evento, lancamento_cod, moeda, idioma_padrao, fonte_label, atualizado_em, data_ate
    config: modo ('leads'|'vendas'), paginas, metas, ... (ver references/data-contract.md)
    segmentos: dict {'genero': df, 'idade': df, 'posicao': df, 'pais': df_pais}"""
    d = dict(schema="fortraffic-dashboard/1", meta=meta, config=config, anuncios=anuncios(gerenciador))
    if leads_df is not None:
        d["leads"] = leads(leads_df)
    if vendas_df is not None:
        d["vendas"] = vendas(vendas_df)
        d["produtos"] = produtos or []
    if segmentos:
        d["segmentos"] = {k: (segmento_pais(v) if k == "pais" else segmento(v)) for k, v in segmentos.items() if v is not None}
    if criativos:
        d["criativos"] = criativos
    if pesquisa:
        d["pesquisa"] = pesquisa
    if lead_scoring:
        d["lead_scoring"] = lead_scoring
    if leitura:
        d["leitura"] = leitura
    return d


def salvar(d, caminho):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    return caminho
