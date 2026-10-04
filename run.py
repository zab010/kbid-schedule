"""매일 실행: 오늘부터 30일 동안의 맞춤스케줄러 공고를 모아 현장 주소를 찾고 사이트를 만든다."""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from kbid.address import file_text, find_site_addresses
from kbid.build_site import build
from kbid.dates import extract_dates
from kbid.geo import geocode, search_place
from kbid.guess import guess, sido_of
from kbid.scrape import Kbid

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "cache.json"
GEO_CACHE = ROOT / "data" / "geo.json"  # 주소 → 좌표 (Actions 캐시, 저장소엔 안 올림)
DAYS = 31  # 오늘 포함 한 달
KST = timezone(timedelta(hours=9))
# 이 시간(분)이 지나면 새 공고 원문은 그만 받고 지금까지 모은 것으로 사이트를 만든다.
# 못 받은 공고는 목록 정보만 싣고 다음 실행 때 이어서 받는다 (Actions 제한 시간 안에 반드시 끝나도록)
BUDGET = float(os.environ.get("BUDGET_MIN", "0") or 0) * 60
RETRY_MISS_DAYS = 2  # 주소를 못 찾은 공고는 이틀 뒤 다시 본다 (정정공고로 첨부가 바뀔 수 있음)
START = time.monotonic()


def over_budget():
    return BUDGET > 0 and time.monotonic() - START > BUDGET


def save_json(path, obj):
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_env():
    f = Path.home() / ".kbid.env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def attachment_order(f):
    """공고문 파일을 먼저, 그다음 한글·PDF 순으로 본다. 내역서(엑셀)는 보지 않는다."""
    n = f["name"]
    if re.search(r"\.(xlsx?|zip|jpg|png|dwg)$", n, re.I):
        return 9
    rank = 0 if "공고" in n else 2 if re.search(r"시방|과업|설계|현장", n) else 4
    return rank + (0 if re.search(r"\.hwpx?$", n, re.I) else 1)


def _specific(found):
    """번지·도로명 번호까지 적힌 주소가 있는지."""
    return any(re.search(r"\d", a) for a, _ in found)


def site_addresses(kb, det, texts):
    """현장 주소를 찾는다. 읽은 본문·첨부 글자는 texts 에 모아 둔다 (일정 찾기에 다시 씀)."""
    best, src = [], ""
    # 1) 상세 페이지에 실린 발주처 공고문 본문
    if det["body_html"]:
        texts.append(file_text("body.html", det["body_html"].encode()))
        best = find_site_addresses(texts[-1])
        src = "공고문 본문" if best else ""
    if _specific(best):
        return best, src
    # 2) 나라장터 첨부 원문 파일 — 본문에 없거나 '○○시 ○○구'까지만 있으면 더 자세한 주소를 찾아본다
    for f in sorted(det["files"], key=attachment_order)[:4]:
        if attachment_order(f) >= 9:
            break
        try:
            texts.append(file_text(f["name"], kb.download(f["url"])))
            found = find_site_addresses(texts[-1])
        except Exception as e:
            print(f"  ! 첨부 받기 실패 {f['name']}: {e}")
            continue
        if found and (not best or _specific(found)):
            best, src = found, f["name"]
            if _specific(best):
                break
    return best, src


def add_coords(notices):
    """현장 주소(첫 번째)를 오픈스트리트맵 검색으로 좌표로 바꿔 notice['geo'] 에 넣는다 (찾은 것은 캐시)."""
    geo = json.loads(GEO_CACHE.read_text(encoding="utf-8")) if GEO_CACHE.exists() else {}
    for n in notices:
        if not n["addresses"]:
            continue
        a = n["addresses"][0]
        if a not in geo:
            if over_budget():
                continue
            try:
                g = geocode(a)
            except Exception as e:
                print(f"  ! 좌표 찾기 실패 {a}: {e}")
                continue
            if not g:
                print(f"  좌표 못 찾음: {a}")
                continue
            geo[a] = g
            if len(geo) % 10 == 0:
                save_json(GEO_CACHE, geo)
        n["geo"] = geo[a]
    save_json(GEO_CACHE, geo)
    guess_places(notices, geo)
    save_json(GEO_CACHE, geo)
    print(f"좌표: {sum(1 for n in notices if n.get('geo'))}건 / 주소 있는 공고 {sum(1 for n in notices if n['addresses'])}건"
          f" / 위치 추정 {sum(1 for n in notices if n.get('guess'))}건")


def guess_places(notices, geo):
    """원문 주소가 없는 공고는 제목·발주처·수요기관 이름으로 위치를 추정한다 (n['guess'], 찾으면 n['geo']).
    모든 공고에 짧은 시·도 이름 n['area'] 를 단다 (사이트의 [대전] 표시·지역 버튼)."""
    def search(q):
        k = "?" + q  # 주소 좌표와 같은 파일에 '?검색어'로 저장, 못 찾은 것도 {} 로 남겨 다시 묻지 않는다
        if k not in geo:
            if over_budget():
                return None
            try:
                geo[k] = search_place(q) or {}
            except Exception as e:
                print(f"  ! 위치 검색 실패 {q}: {e}")
                return None
        return geo[k] or None

    for n in notices:
        n.pop("guess", None)
        if n["addresses"]:
            n["area"] = sido_of(n["addresses"][0])
            continue
        g = guess(n, search)
        if g:
            n["guess"] = {"text": g["text"], "how": g["how"]}
            if g["geo"]:
                n["geo"] = g["geo"]
        n["area"] = (g or {}).get("sido") or sido_of(n.get("region", ""))


def main():
    load_env()
    kb = Kbid(os.environ["KBID_ID"], os.environ["KBID_PW"])
    for name, query in kb.login():
        print(f"로그인 완료, 탭 「{name}」 조건: {query}")

    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    today = datetime.now(KST).date()
    notices, seen = [], {}
    fetched = skipped = 0
    for i in range(DAYS):
        day = today + timedelta(days=i)
        rows = [(tab, row) for tab, query in kb.tabs for row in kb.day_list(day, query)]
        if rows:
            print(f"{day}: {len(rows)}건")
        for tab, row in rows:
            key = f"{row['bid_no']}-{row['bid_seq']}"
            if key in seen:
                # 여러 탭에 함께 나온 공고는 한 번만 싣고 탭 이름만 더한다
                if tab not in seen[key]["tabs"]:
                    seen[key]["tabs"].append(tab)
                continue
            info = cache.get(key)
            if info and info.get("miss") and info["miss"] <= (today - timedelta(days=RETRY_MISS_DAYS)).isoformat():
                info = None  # 주소를 못 찾았던 공고 — 며칠 지났으니 다시 본다
            if info and "dates" not in info and not over_budget():
                # 일정 항목이 생기기 전에 저장한 공고 — 상세 화면만 다시 받아 일정을 채운다
                try:
                    det = kb.detail(row["bid_no"], row["bid_seq"])
                    body = file_text("body.html", det["body_html"].encode()) if det["body_html"] else ""
                    info["dates"] = extract_dates(det["fields"], body)
                except requests.RequestException as e:
                    # 일정 없이 싣고 다음 실행 때 다시 채운다
                    print(f"  {row.get('title', key)} → 상세 받기 실패, 일정은 다음에: {e}")
            if not info and over_budget():
                skipped += 1
                info = {"no": "", "demand": "", "deadline": "", "open": "", "price": "", "addresses": [],
                        "address_key": "", "address_file": "", "files": [], "dates": {}}
            elif not info:
                try:
                    det = kb.detail(row["bid_no"], row["bid_seq"])
                except requests.RequestException as e:
                    print(f"  {row.get('title', key)} → 상세 받기 실패, 다음에 다시: {e}")
                    continue
                fd = det["fields"]
                texts = []
                found, src = site_addresses(kb, det, texts)
                no = re.search(r"[A-Z0-9]{6,}-\d{3}|\d{8,}-\d{2,}", fd.get("발주처 공고번호", ""))
                info = {
                    "no": no.group(0) if no else fd.get("발주처 공고번호", ""),
                    "demand": fd.get("수요기관", ""),
                    "deadline": fd.get("투찰마감일시", fd.get("투찰마감일", "")),
                    "open": fd.get("입찰(개찰) 일시", fd.get("입찰(개찰)일", "")),
                    "price": fd.get("기초금액") or fd.get("추정가격", ""),
                    "addresses": [a for a, _ in found],
                    "address_key": found[0][1] if found else "",
                    "address_file": src,
                    "files": [f for f in det["files"] if attachment_order(f) < 9],
                    "dates": extract_dates(fd, *texts),
                }
                # 못 찾은 공고도 저장해 두되 날짜를 적어 RETRY_MISS_DAYS 뒤 다시 본다
                cache[key] = info if found else {**info, "miss": today.isoformat()}
                fetched += 1
                if fetched % 10 == 0:
                    save_json(CACHE, cache)  # 중간에 끊겨도 받은 만큼은 다음 실행에 남도록
                print(f"  {row['title'][:40]} → {info['addresses'] or '주소 못 찾음'}")
            seen[key] = {
                "key": key, "date": day.isoformat(), "tabs": [tab],
                "title": row["title"], "agency": row["agency"], "kind": row["kind"],
                "region": row["region"], **{k: v for k, v in info.items() if k != "miss"},
            }
            notices.append(seen[key])

    save_json(CACHE, cache)
    if skipped:
        print(f"시간 제한으로 원문을 못 받은 공고 {skipped}건 — 목록 정보만 싣고 다음 실행 때 이어서 받음")
    add_coords(notices)
    data = {
        "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "range_from": today.isoformat(),
        "range_to": (today + timedelta(days=DAYS - 1)).isoformat(),
        "tabs": [name for name, _ in kb.tabs],
        "notices": notices,
    }
    (ROOT / "data" / "notices.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    out = build(data, os.environ.get("SITE_PASSWORD") or "1234")
    found = sum(1 for n in notices if n["addresses"])
    print(f"완료: 공고 {len(notices)}건, 현장 주소 찾음 {found}건 → {out}")


if __name__ == "__main__":
    main()
