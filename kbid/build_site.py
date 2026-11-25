"""공고 JSON을 비밀번호로 암호화해 docs/index.html 로 만든다."""
import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent.parent
ITER = 300_000


def encrypt(obj, password):
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt, ITER).derive(password.encode())
    data = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode(), None)
    b = lambda x: base64.b64encode(x).decode()
    return {"salt": b(salt), "iv": b(iv), "iter": ITER, "data": b(data)}


def build(data, password, out=ROOT / "docs" / "index.html"):
    # 브이월드 키(사이트 주소에서만 쓰이게 발급)는 암호화된 자료 안에 넣는다. 없으면 사이트는 오픈스트리트맵 좌표만 쓴다
    data = {**data, "vworld_key": os.environ.get("VWORLD_KEY", "")}
    tpl = (ROOT / "site" / "template.html").read_text(encoding="utf-8")
    html = tpl.replace("__PAYLOAD__", json.dumps(encrypt(data, password)))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    (out.parent / ".nojekyll").touch()
    (out.parent / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    return out


if __name__ == "__main__":
    import sys
    src = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data" / "notices.json")
    print(build(json.loads(src.read_text(encoding="utf-8")), os.environ.get("SITE_PASSWORD", "1234")))
