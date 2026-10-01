"""현장 주소 → 좌표 (카카오 로컬 API). 키는 환경변수 KAKAO_REST_KEY."""
import re
import time

import requests

API = "https://dapi.kakao.com/v2/local/search/{}.json"


def _clean(addr):
    """'대전시 동구 중앙로 242, 국가철도공단 10층' → '대전시 동구 중앙로 242' 처럼 건물·층·괄호를 뗀다."""
    a = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", addr)
    a = re.split(r"[,，]| 외\s*\d| 일원| 일대| 내\b", a)[0]
    # 번지·도로명 번호 뒤에 붙은 건물 이름은 뗀다
    m = re.match(r"(.*?\d+(?:-\d+)?(?:번지)?)(?=[\s.]|$)", a)
    return re.sub(r"\s+", " ", (m.group(1) if m else a)).strip(" .")


def _search(kind, query, key):
    time.sleep(0.1)
    r = requests.get(API.format(kind), params={"query": query, "size": 1},
                     headers={"Authorization": f"KakaoAK {key}"}, timeout=30)
    r.raise_for_status()
    docs = r.json().get("documents") or []
    return (float(docs[0]["y"]), float(docs[0]["x"])) if docs else None


def geocode(addr, key):
    """좌표 {lat, lon, q, level}. level: 'addr' 주소 일치, 'area' 읍·면·동/시·군·구 수준, 'place' 장소 이름 검색."""
    q = _clean(addr)
    if not q:
        return None
    hit = _search("address", q, key)
    if hit:
        return {"lat": hit[0], "lon": hit[1], "q": q, "level": "addr"}
    # 주소로 안 나오면 장소 이름(원래 문자열)으로
    hit = _search("keyword", addr[:80], key)
    if hit:
        return {"lat": hit[0], "lon": hit[1], "q": addr[:80], "level": "place"}
    # 그래도 없으면 뒤에서부터 한 단어씩 줄여 시·군·구/동 수준이라도
    words = q.split()
    while len(words) > 1:
        words.pop()
        hit = _search("address", " ".join(words), key)
        if hit:
            return {"lat": hit[0], "lon": hit[1], "q": " ".join(words), "level": "area"}
    return None
