#!/usr/bin/env python3
"""Coleta as fontes do dashboard SEM Claude (modo GitHub Actions) e grava os mesmos arquivos
que a Rotina grava com os conectores MCP. Assim o gerar_data_<id>.py do cliente roda igual nos dois modos.

Saída (em FT_BASE, padrão /tmp):
  meta2/ads.json       nível anúncio, 1 linha por dia: date_start, campaign_name, adset_name, name, effective_status,
                       amount_spent, impressions, link_click, landing_page_view, lead, initiate_checkout, purchase
  meta2/idadegen.json  nível conjunto, breakdowns age+gender: date_start, campaign_name, adset_name, age, gender, amount_spent, lead
  meta2/posicao.json   nível conjunto, breakdowns publisher_platform+platform_position: idem
  <nome>.xlsx          cada planilha de SHEETS exportada do Google Drive (ex.: leads.xlsx, pesquisa.xlsx)
  leitura.json         texto "leitura" do data JSON já publicado (a Rotina diária escreve; o Actions só preserva)

Variáveis de ambiente (segredos ficam em Settings → Secrets and variables → Actions, NUNCA no repositório):
  META_ACCESS_TOKEN  (secret)   token de usuário do sistema do Business Manager com ads_read
  META_AD_ACCOUNT_ID (variable) ex.: act_123456789 (com ou sem "act_")
  META_SINCE         (variable) primeiro dia do lançamento, yyyy-mm-dd
  META_API_VERSION   (opcional) padrão v23.0
  META_RESULTADO     (opcional) action_type contado como resultado, padrão "lead" (cai para pixel lead se vazio)
  GOOGLE_SA_JSON     (secret)   JSON da conta de serviço; compartilhe as planilhas com o e-mail dela (leitor)
  SHEETS             (variable) JSON {"leads": "<id do arquivo no Drive>", "pesquisa": "<id>"}
  DATA_URL           (opcional) URL pública do data JSON atual, para preservar a leitura
  FT_BASE            (opcional) pasta de saída, padrão /tmp
"""
import json, os, sys, time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import requests

BASE = os.environ.get('FT_BASE', '/tmp')
VER = os.environ.get('META_API_VERSION', 'v23.0')
RES = os.environ.get('META_RESULTADO', 'lead')
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def falha(msg):
    sys.exit('ERRO: ' + msg)


def env(k, obrig=True):
    v = os.environ.get(k, '').strip()
    if obrig and not v:
        falha(f'variável {k} não definida (Settings → Secrets and variables → Actions)')
    return v


# ---------------- Meta Ads (Graph API) ----------------
def graph(url, params=None, tentativas=4):
    for i in range(tentativas):
        r = requests.get(url, params=params, timeout=120)
        if r.ok:
            return r.json()
        err = (r.json() if r.headers.get('content-type', '').startswith('application/json') else {}).get('error', {})
        if r.status_code in (400, 401, 403) and err.get('code') in (190, 10, 200, 100):
            falha(f"Meta recusou ({err.get('code')}): {err.get('message')}. Token expirado/sem ads_read ou conta errada.")
        time.sleep(5 * (i + 1))  # limite de taxa (17/4/80004) e instabilidade
    falha(f'Meta API falhou: {r.status_code} {r.text[:300]}')


def paginar(url, params):
    out, j = [], graph(url, params)
    while True:
        out += j.get('data', [])
        nxt = (j.get('paging') or {}).get('next')
        if not nxt:
            return out
        j = graph(nxt)


def acao(r, *tipos):
    m = {a.get('action_type'): a.get('value') for a in (r.get('actions') or [])}
    for t in tipos:
        if m.get(t) not in (None, ''):
            return int(float(m[t]))
    return 0


def resultado(r):
    return acao(r, RES, 'offsite_conversion.fb_pixel_lead', 'onsite_conversion.lead_grouped')


def insights(conta, since, until, level, fields, breakdowns=None):
    """Janela de 7 em 7 dias: a API síncrona estoura tempo em períodos longos."""
    url, rows, d = f'https://graph.facebook.com/{VER}/{conta}/insights', [], since
    while d <= until:
        fim = min(d + timedelta(days=6), until)
        p = dict(access_token=TOKEN, level=level, time_increment=1, limit=500, fields=','.join(fields),
                 time_range=json.dumps({'since': d.isoformat(), 'until': fim.isoformat()}))
        if breakdowns:
            p['breakdowns'] = ','.join(breakdowns)
        rows += paginar(url, p)
        d = fim + timedelta(days=1)
    return rows


def coletar_meta():
    conta = env('META_AD_ACCOUNT_ID')
    conta = conta if conta.startswith('act_') else 'act_' + conta
    since = date.fromisoformat(env('META_SINCE'))
    # "hoje" no fuso da conta de anúncios (o runner roda em UTC); inclui o dia corrente parcial,
    # é isso que dá a atualização de hora em hora
    tz = graph(f'https://graph.facebook.com/{VER}/{conta}', dict(access_token=TOKEN, fields='timezone_name')).get('timezone_name') or 'UTC'
    until = datetime.now(ZoneInfo(tz)).date()
    base = ['campaign_name', 'adset_name', 'spend', 'actions']
    st = {a['id']: a.get('effective_status', '') for a in paginar(
        f'https://graph.facebook.com/{VER}/{conta}/ads', dict(access_token=TOKEN, fields='id,effective_status', limit=500))}
    ads = [dict(date_start=r['date_start'], campaign_name=r.get('campaign_name', ''), adset_name=r.get('adset_name', ''),
                name=r.get('ad_name', ''), effective_status=st.get(r.get('ad_id'), ''), amount_spent=float(r.get('spend') or 0),
                impressions=int(r.get('impressions') or 0), link_click=int(r.get('inline_link_clicks') or 0),
                landing_page_view=acao(r, 'landing_page_view', 'omni_landing_page_view'), lead=resultado(r),
                initiate_checkout=acao(r, 'offsite_conversion.fb_pixel_initiate_checkout', 'initiate_checkout', 'omni_initiated_checkout'),
                purchase=acao(r, 'offsite_conversion.fb_pixel_purchase', 'purchase', 'omni_purchase'))
           for r in insights(conta, since, until, 'ad', base + ['ad_id', 'ad_name', 'impressions', 'inline_link_clicks'])]

    def seg(bd):
        return [dict(date_start=r['date_start'], campaign_name=r.get('campaign_name', ''), adset_name=r.get('adset_name', ''),
                     amount_spent=float(r.get('spend') or 0), lead=resultado(r), **{k: r.get(k, '') for k in bd})
                for r in insights(conta, since, until, 'adset', base, bd)]

    os.makedirs(f'{BASE}/meta2', exist_ok=True)
    for nome, rows in (('ads', ads), ('idadegen', seg(['age', 'gender'])), ('posicao', seg(['publisher_platform', 'platform_position']))):
        json.dump(rows, open(f'{BASE}/meta2/{nome}.json', 'w', encoding='utf-8'), ensure_ascii=False)
        print(f'meta2/{nome}.json: {len(rows)} linhas')
    print(f"gasto total: {sum(r['amount_spent'] for r in ads):.2f} | período {since} → {until}")


# ---------------- Google Drive (planilhas) ----------------
def coletar_planilhas():
    sheets = json.loads(env('SHEETS'))
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    cred = service_account.Credentials.from_service_account_info(
        json.loads(env('GOOGLE_SA_JSON')), scopes=['https://www.googleapis.com/auth/drive.readonly'])
    s = AuthorizedSession(cred)
    for nome, fid in sheets.items():
        meta = s.get(f'https://www.googleapis.com/drive/v3/files/{fid}', params={'fields': 'mimeType,name', 'supportsAllDrives': 'true'})
        if not meta.ok:
            falha(f'planilha {nome} ({fid}): {meta.status_code}. Compartilhe com {cred.service_account_email} como leitor.')
        nativa = meta.json()['mimeType'] == 'application/vnd.google-apps.spreadsheet'
        r = s.get(f'https://www.googleapis.com/drive/v3/files/{fid}' + ('/export' if nativa else ''),
                  params={'mimeType': XLSX} if nativa else {'alt': 'media', 'supportsAllDrives': 'true'})
        if not r.ok:
            falha(f'download de {nome} falhou: {r.status_code} {r.text[:200]}')
        open(f'{BASE}/{nome}.xlsx', 'wb').write(r.content)
        print(f'{nome}.xlsx: {len(r.content) // 1024} KB ({meta.json()["name"]})')


def preservar_leitura():
    url = os.environ.get('DATA_URL', '').strip()
    if not url:
        return
    try:
        lt = requests.get(url, params={'t': int(time.time())}, timeout=30).json().get('leitura')
        if lt:
            json.dump(lt, open(f'{BASE}/leitura.json', 'w', encoding='utf-8'), ensure_ascii=False)
            print('leitura preservada do JSON publicado')
    except Exception as e:  # sem leitura o dashboard funciona normalmente
        print('aviso: leitura não preservada:', e)


if __name__ == '__main__':
    TOKEN = env('META_ACCESS_TOKEN')
    os.makedirs(BASE, exist_ok=True)
    coletar_meta()
    coletar_planilhas()
    preservar_leitura()
    print('coleta ok', datetime.now().strftime('%d/%m/%Y %H:%M'))
