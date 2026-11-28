"""사이트 모양만 다시 만든다: 지금 게시된 docs/index.html을 비밀번호로 풀어 공고 자료를 꺼내고,
지금 site/template.html로 다시 암호화해 docs/index.html을 쓴다. (공고를 새로 받지 않음 — 템플릿을 고쳤을 때 바로 반영용)

    SITE_PASSWORD=... python -m kbid.rebuild_site
"""
import base64
import json
import os
import re

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .build_site import ROOT, build


def current_data(password):
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"const PAYLOAD = (\{.*?\});", html)
    if not m:
        raise SystemExit("docs/index.html 에서 공고 자료(PAYLOAD)를 찾지 못했습니다")
    p = json.loads(m.group(1))
    b = base64.b64decode
    key = PBKDF2HMAC(hashes.SHA256(), 32, b(p["salt"]), p["iter"]).derive(password.encode())
    return json.loads(AESGCM(key).decrypt(b(p["iv"]), b(p["data"]), None))


if __name__ == "__main__":
    pw = os.environ.get("SITE_PASSWORD")   # GitHub Actions 비밀값(Secrets)에서만 받는다
    if not pw:
        raise SystemExit("SITE_PASSWORD 환경 변수가 없습니다")
    data = current_data(pw)
    print(build(data, pw), "· 공고", len(data.get("notices", [])), "건 · 마지막 갱신", data.get("updated"))
