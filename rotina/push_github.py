#!/usr/bin/env python3
"""Publica arquivos do dashboard num repositório GitHub (GitHub Pages) pela API REST de contents.

Uso:
  export GITHUB_TOKEN=...            # token com escopo repo; NUNCA escreva o token em arquivo, prompt ou chat
  python3 push_github.py --repo dono/repositorio --dir docs \
      data-meulancamento.json launches.json [index.html] [imgs/foto.jpg ...]

  --branch main      branch de destino (padrão main)
  --dir docs         pasta servida pelo Pages ('' = raiz)
  --dry-run          mostra o que faria, sem chamar a API
  --msg "texto"      mensagem do commit (padrão: Dashboard dd/mm/aaaa HH:MM)

Cada arquivo é atualizado com o sha atual (ou criado). Só usa a biblioteca padrão, então roda
dentro das Rotinas do Claude (nuvem) sem instalar nada. Arquivos binários (imagens) funcionam.
"""
import argparse, base64, json, os, sys, time, urllib.error, urllib.request
from datetime import datetime

API = "https://api.github.com"


def _req(method, url, token, payload=None, tentativas=3):
    h = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json", "User-Agent": "ft-dashboard-bot"}
    data = json.dumps(payload).encode() if payload is not None else None
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method), timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", "ignore")[:300]
            if e.code == 404 and method == "GET":
                return 404, {}
            if e.code in (409, 500, 502, 503, 504) and i < tentativas - 1:  # conflito de sha / instabilidade: tenta de novo
                time.sleep(2 * (i + 1))
                continue
            if e.code in (401, 403):
                sys.exit(f"GitHub recusou ({e.code}). Token inválido, sem escopo 'repo' ou revogado por exposição. Gere outro. {corpo}")
            sys.exit(f"Erro {e.code} em {method} {url}: {corpo}")
    sys.exit(f"Falhou após {tentativas} tentativas: {url}")


def put_file(repo, branch, caminho_remoto, caminho_local, msg, token, dry):
    conteudo = open(caminho_local, "rb").read()
    if dry:
        print(f"[dry-run] {caminho_local} -> {repo}:{branch}/{caminho_remoto} ({len(conteudo)//1024} KB)")
        return
    url = f"{API}/repos/{repo}/contents/{caminho_remoto}"
    st, atual = _req("GET", f"{url}?ref={branch}", token)
    payload = {"message": msg, "content": base64.b64encode(conteudo).decode(), "branch": branch}
    if st == 200 and atual.get("sha"):
        payload["sha"] = atual["sha"]
    _, r = _req("PUT", url, token, payload)
    print(f"ok {caminho_remoto} commit {r['commit']['sha'][:7]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("arquivos", nargs="+")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--dir", default="docs")
    ap.add_argument("--msg", default=f"Dashboard {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    tok = os.environ.get("GITHUB_TOKEN", "")
    if not tok and not a.dry_run:
        sys.exit("Defina GITHUB_TOKEN no ambiente (não passe o token como argumento).")
    for f in a.arquivos:
        if not os.path.isfile(f):
            sys.exit(f"Arquivo não encontrado: {f}")
        remoto = "/".join(p for p in (a.dir.strip("/"), f.lstrip("./")) if p)
        put_file(a.repo, a.branch, remoto, f, a.msg, tok, a.dry_run)
