#!/usr/bin/env python3
"""Gera docs/data/<id>/debriefing.json de um lançamento encerrado.

Uso:
  python3 rotina/gerar_debriefing.py --id plf-oct26 --label "PLF - Out 2026" \
      --data docs/data-plf-oct26.json --compradores /caminho/compradores.xlsx \
      --ventas 41 --facturacion 106477 [--fase "Replay=499.97" ...]

Entradas:
  --data         JSON do dashboard ao vivo (anuncios = gasto diário por anúncio; leads = leads por UTM).
  --compradores  planilha do cliente: Venta, Nombre, Email, utm_source, utm_medium (conjunto),
                 utm_term (campanha), utm_content (criativo), utm_campaign. Não é versionada (dados pessoais).
  --ventas / --facturacion  totais oficiais informados pelo cliente.
  --fase         gasto fora da captação (Recordatório, Assistência, Replay, Inscripciones Abiertas), vindo do Meta Ads.

Regras (iguais às do debriefing AGO26):
  - Caliente/Frio: comprador com utm_source pago (ig, fb, th, an) e HOT/COLD no nome da campanha.
  - Orgánico: comprador encontrado na planilha de leads sem UTM de anúncio (whatsapp, email, instagram).
  - Não encontrado: comprou com e-mail diferente do cadastro. Ventas/faturamento desta linha são o
    resíduo entre o total oficial e o atribuído.
  - Gasto por público/criativo é o do conjunto/anúncio inteiro (somado entre campanhas).
"""
import argparse, json, os, collections as C
import openpyxl

PAGOS = {'ig', 'fb', 'th', 'an'}
FASES = ['Captación', 'Recordatório', 'Assistência', 'Replay', 'Inscripciones Abiertas']

def div(a, b, nd=4):
    return round(a / b, nd) if b else None

def linha(nome, inv, leads, ventas, ticket, fact=None):
    fact = ventas * ticket if fact is None else fact
    return {'nome': nome, 'inversion': round(inv, 2), 'leads': leads, 'cpl': div(inv, leads, 2) if inv else None,
            'ventas': ventas, 'cac': (div(inv, ventas, 2) if ventas else None) if inv else (0 if ventas else None),
            'tasa_conversion': (ventas / leads) if leads else 0, 'facturacion': fact,
            'roas': div(fact, inv) if inv else None}

def main():
    ap = argparse.ArgumentParser()
    for a in ('--id', '--label', '--data', '--compradores'): ap.add_argument(a, required=True)
    ap.add_argument('--ventas', type=int, required=True)
    ap.add_argument('--facturacion', type=float, required=True)
    ap.add_argument('--fase', action='append', default=[])
    ap.add_argument('--status', default='vendas encerradas')
    ap.add_argument('--atualizado', required=True)
    ap.add_argument('--obs', default='')
    a = ap.parse_args()

    d = json.load(open(a.data, encoding='utf-8'))
    A, L = d['anuncios'], d['leads']
    ticket = round(a.facturacion / a.ventas)
    fact_total = int(a.facturacion) if a.facturacion == int(a.facturacion) else a.facturacion

    # ---- gasto
    sp_capt = sum(x['sp'] for x in A)
    sp_temp = C.defaultdict(float); sp_conj = C.defaultdict(float); sp_ad = C.defaultdict(float)
    for x in A:
        up = x['c'].upper()
        sp_temp['Caliente' if 'HOT' in up else 'Frio'] += x['sp']
        sp_conj[x['a']] += x['sp']; sp_ad[x['an']] += x['sp']
    fases = {f: 0.0 for f in FASES}; fases['Captación'] = sp_capt
    for f in a.fase:
        k, v = f.split('='); assert k in fases, k; fases[k] = float(v)
    inv_total = sum(fases.values())

    # ---- leads
    ld = C.Counter()
    for l in L:
        if l['t'] == 'HOT': ld['Caliente'] += l['n']
        elif l['t'] == 'COLD': ld['Frio'] += l['n']
        elif l['a'] in ('whatsapp', 'email', 'instagram') and not l['rt']: ld['Orgánico'] += l['n']
        else: ld['Sin Trackeo'] += l['n']
    leads_total = sum(ld.values()); track = ld['Caliente'] + ld['Frio']

    # ---- compradores
    ws = openpyxl.load_workbook(a.compradores, data_only=True).active
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0]]
    comp = []; vt = C.Counter(); vconj = C.Counter(); vad = C.Counter(); vorg = C.Counter()
    for r in rows:
        src, med, term, cont = [(x or '').strip() for x in r[3:7]]
        if src in PAGOS:
            t = 'Caliente' if 'HOT' in term.upper() else 'Frio'
            vt[t] += 1; vconj[med] += 1; vad[cont] += 1
            comp.append({'encontrado': True, 'match_por': 'UTM informada pelo cliente', 'temperatura': t, 'canal': src,
                         'rastreado': True, 'campanha': term, 'conjunto': med, 'criativo': cont})
        elif med:
            vt['Orgánico'] += 1; vorg[med] += 1
            comp.append({'encontrado': True, 'match_por': 'UTM informada pelo cliente', 'temperatura': 'Organico',
                         'canal': 'sem_rastreio', 'rastreado': False, 'campanha': term, 'conjunto': med, 'criativo': cont})
        else:
            comp.append({'encontrado': False})
    comp.sort(key=lambda c: not c['encontrado'])
    pagas = vt['Caliente'] + vt['Frio']; achadas = pagas + vt['Orgánico']
    nao = a.ventas - achadas

    temp = [linha('Caliente', sp_temp['Caliente'], ld['Caliente'], vt['Caliente'], ticket),
            linha('Frio', sp_temp['Frio'], ld['Frio'], vt['Frio'], ticket),
            linha('Orgánico', 0, ld['Orgánico'], vt['Orgánico'], ticket),
            linha('Sin Trackeo', 0, ld['Sin Trackeo'], 0, ticket)]
    tot = linha('TOTAL', sp_capt, leads_total, achadas, ticket)
    plat = linha('', sp_capt, leads_total, pagas, ticket); plat.pop('nome')
    zero = {'inversion': 0, 'leads': 0, 'cpl': None, 'ventas': 0, 'cac': None, 'tasa_conversion': 0, 'facturacion': 0, 'roas': None}
    imp = sum(x['imp'] for x in A); lc = sum(x['lc'] for x in A); pv = sum(x['pv'] for x in A)

    out = {
        'launch': a.id, 'label': a.label, 'status': a.status, 'atualizado_em': a.atualizado, 'ticket_price': ticket,
        'metricas_gerais': {'inversion_total': round(inv_total, 2), 'leads': leads_total, 'cpl': div(sp_capt, leads_total, 2),
                            'total_ventas': a.ventas, 'reembolso': 0, 'ventas_trackeadas': achadas,
                            'cac': div(inv_total, a.ventas, 2), 'tasa_conversion': a.ventas / leads_total,
                            'facturacion': fact_total, 'roas': div(a.facturacion, inv_total)},
        'plataforma': {'meta_ads': plat, 'google_ads': zero, 'total': dict(plat)},
        'temperatura': temp, 'temperatura_total': tot,
        'nao_encontrado': {'nome': 'Não encontrado na planilha de leads', 'ventas': nao,
                           'facturacion': fact_total - achadas * ticket,
                           'nota': 'Vendas confirmadas de quem comprou com e-mail diferente do cadastro: sem lead correspondente, origem não identificada. Ventas e faturamento desta linha são o resíduo entre o total oficial e o atribuído às demais temperaturas.'},
        'trackeamento': {'leads': {'total': leads_total, 'trackeado': track, 'sin_trackeo': leads_total - track,
                                   'pct_trackeado': track / leads_total, 'pct_sin_trackeo': 1 - track / leads_total},
                         'ventas': {'total': a.ventas, 'encontradas_na_planilha': achadas, 'nao_encontradas': nao,
                                    'pct_encontradas': achadas / a.ventas}},
        'gasto_por_fase': [{'fase': f, 'valor': round(v, 2), 'pct': v / inv_total} for f, v in fases.items()],
        'metricas_lancamento': {'cpm': div(sp_capt * 1000, imp, 2), 'connect_rate': div(pv, lc), 'conversao_lp': div(track, pv), 'ctr': div(lc, imp)},
        'publicos_com_venda': [{'publico': k, 'inversion': round(sp_conj[k], 2), 'ventas': v, 'facturacion': v * ticket,
                                'roas': div(v * ticket, sp_conj[k])} for k, v in vconj.most_common()],
        'publicos_organico': [{'origem': k, 'ventas': v} for k, v in vorg.most_common()],
        'criativos_com_venda': [{'ad': k, 'ventas': v, 'gasto': round(sp_ad[k], 2), 'cpa': div(sp_ad[k], v, 2),
                                 'facturacion': v * ticket, 'roas': div(v * ticket, sp_ad[k])} for k, v in vad.most_common()],
        'compradores': comp, 'obs': a.obs,
        'faturamento_detalhe': {'ventas_principal': a.ventas, 'ticket_principal': ticket, 'faturamento_principal': fact_total,
                                'ventas_upsell': 0, 'ticket_upsell': 0, 'faturamento_upsell': 0, 'faturamento_total': fact_total},
    }
    dest = os.path.join('docs', 'data', a.id, 'debriefing.json')
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    json.dump(out, open(dest, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'{dest}: lista {len(rows)} compradores | pagas {pagas} (HOT {vt["Caliente"]}, COLD {vt["Frio"]}) | '
          f'orgânico {vt["Orgánico"]} | não encontradas na lista {len(rows) - achadas} (resíduo oficial {nao}) | '
          f'gasto {inv_total:.2f} | leads {leads_total}')

if __name__ == '__main__':
    main()
