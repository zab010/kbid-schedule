"""현장 주소 → 좌표. 가입·키가 필요 없는 오픈스트리트맵 검색(Nominatim, 안 되면 Photon)을 쓴다.
Nominatim 이용 정책: 1초에 1번 이하, 앱 이름이 담긴 User-Agent, 결과는 캐시해서 다시 묻지 않기."""
import re
import time

import requests

UA = {"User-Agent": "kbid-schedule/1.0 (noncommercial bid notice map; https://github.com/zab010/kbid-schedule)"}
_last = [0.0]


def _wait():
    d = time.time() - _last[0]
    if d < 1.1:
        time.sleep(1.1 - d)
    _last[0] = time.time()


def _clean(addr):
    """'대전시 동구 중앙로 242, 국가철도공단 10층' → '대전시 동구 중앙로 242' 처럼 건물·층·괄호를 뗀다."""
    a = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", addr)
    a = re.split(r"[,，]| 외\s*\d| 일원| 일대| 내\b", a)[0]
    # 번지·도로명 번호 뒤에 붙은 건물 이름은 뗀다
    m = re.match(r"(.*?\d+(?:-\d+)?(?:번지)?)(?=[\s.]|$)", a)
    a = re.sub(r"\s+", " ", (m.group(1) if m else a)).strip(" .")
    return re.sub(r"(\d)번지$", r"\1", a)


def _nominatim(q):
    _wait()
    r = requests.get("https://nominatim.openstreetmap.org/search", headers=UA, timeout=30,
                     params={"q": q, "format": "json", "limit": 1, "countrycodes": "kr"})
    r.raise_for_status()
    j = r.json()
    return (float(j[0]["lat"]), float(j[0]["lon"])) if j else None


def _photon(q):
    time.sleep(0.5)
    r = requests.get("https://photon.komoot.io/api/", headers=UA, timeout=30,
                     params={"q": q, "limit": 1, "bbox": "124.5,33,131.9,38.7"})  # 한국 범위
    r.raise_for_status()
    f = r.json().get("features") or []
    if not f:
        return None
    lon, lat = f[0]["geometry"]["coordinates"]
    return lat, lon


def geocode(addr):
    """좌표 {lat, lon, q, level}. level: 'addr' 주소 그대로 찾음, 'area' 동·읍·면이나 시·군·구까지만 찾음."""
    # '○○수련마을 주2동 / 중구 방아미로 131' 처럼 '/'로 이어진 경우 번호가 있는 쪽을 쓴다
    parts = [p for p in addr.split("/") if re.search(r"\d", p)] or [addr]
    return _geocode_one(parts[-1])


def _geocode_one(addr):
    q = _clean(addr)
    if not q:
        return None
    for find in (_nominatim, _photon):
        try:
            hit = find(q)
        except requests.RequestException:
            hit = None
        if hit:
            return {"lat": hit[0], "lon": hit[1], "q": q, "level": "addr"}
    # 뒤에서부터 한 단어씩 줄여 동·구 수준이라도
    words = q.split()
    while len(words) > 2:
        words.pop()
        hit = _nominatim(" ".join(words))
        if hit:
            return {"lat": hit[0], "lon": hit[1], "q": " ".join(words), "level": "area"}
    return None


def search_place(q):
    """기관·지명 검색 → {lat, lon, sido, text}. text 는 '경기도 고양시 일산서구 대화동 (킨텍스)' 꼴."""
    from kbid.guess import sido_of
    _wait()
    r = requests.get("https://nominatim.openstreetmap.org/search", headers=UA, timeout=30,
                     params={"q": q, "format": "json", "limit": 1, "countrycodes": "kr", "accept-language": "ko"})
    r.raise_for_status()
    j = r.json()
    if not j:
        return None
    parts = [p.strip() for p in j[0]["display_name"].split(",")]
    parts = [p for p in parts if p not in ("대한민국", "South Korea") and not re.fullmatch(r"\d{5}", p)]
    area = parts[1:][::-1] if len(parts) > 1 else parts
    text = " ".join(area) + (f" ({parts[0]})" if len(parts) > 1 else "")
    sido = next((sido_of(p) for p in area if sido_of(p)), "")
    return {"lat": float(j[0]["lat"]), "lon": float(j[0]["lon"]), "sido": sido, "text": text}
