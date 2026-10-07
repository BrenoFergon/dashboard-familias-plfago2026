#!/usr/bin/env python3
"""Grava respostas de conectores MCP em arquivos que o gerador lê, sem a rotina reescrever dados à mão.

  python3 rotina/salvar_mcp.py drive DESTINO.xlsx RESPOSTA
      RESPOSTA = arquivo onde a ferramenta download_file_content salvou a resposta
      (ou o JSON gravado com Write quando a resposta veio direto na conversa).
      Decodifica o base64 e grava a planilha.

  python3 rotina/salvar_mcp.py meta DESTINO.json PAGINA1 [PAGINA2 ...]
      Cada PAGINA = arquivo com a resposta de ads_get_ad_entities (uma por página de paginação).
      Junta todas as linhas num único array e grava.
"""
import base64, json, sys


def ler(caminho):
    obj = json.loads(open(caminho, encoding='utf-8').read())
    if isinstance(obj, list) and obj and isinstance(obj[0], dict) and 'text' in obj[0]:
        obj = json.loads(obj[0]['text'])
    return obj


def linhas_meta(obj):
    if isinstance(obj, dict):
        obj = obj.get('ad_entities', obj.get('data', obj))
    if isinstance(obj, str):
        obj = json.loads(obj)
    if isinstance(obj, dict):
        obj = obj.get('data', [])
    return obj or []


if __name__ == '__main__':
    modo, destino, fontes = sys.argv[1], sys.argv[2], sys.argv[3:]
    if modo == 'drive':
        open(destino, 'wb').write(base64.b64decode(ler(fontes[0])['content']))
        print('ok', destino)
    elif modo == 'meta':
        rows = [r for f in fontes for r in linhas_meta(ler(f))]
        json.dump(rows, open(destino, 'w', encoding='utf-8'), ensure_ascii=False)
        print('ok', destino, len(rows), 'linhas', 'datas', min((r.get('date_start', '') for r in rows), default='-'), '→',
              max((r.get('date_start', '') for r in rows), default='-'))
    else:
        sys.exit('modo deve ser drive ou meta')
