"""매일 실행: 오늘부터 30일 동안의 맞춤스케줄러 공고를 모아 현장 주소를 찾고 사이트를 만든다."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kbid.address import file_text, find_site_addresses
from kbid.build_site import build
from kbid.dates import extract_dates
from kbid.geo import geocode
from kbid.scrape import Kbid

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "cache.json"
GEO_CACHE = ROOT / "data" / "geo.json"  # 주소 → 좌표 (Actions 캐시, 저장소엔 안 올림)
DAYS = 31  # 오늘 포함 한 달
KST = timezone(timedelta(hours=9))


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
    """현장 주소(첫 번째)를 카카오 API로 좌표로 바꿔 notice['geo'] 에 넣는다. 키가 없으면 건너뛴다."""
    key = os.environ.get("KAKAO_REST_KEY")
    if not key:
        print("KAKAO_REST_KEY 없음 — 좌표 찾기 건너뜀")
        return
    geo = json.loads(GEO_CACHE.read_text(encoding="utf-8")) if GEO_CACHE.exists() else {}
    for n in notices:
        if not n["addresses"]:
            continue
        a = n["addresses"][0]
        if a not in geo:
            try:
                g = geocode(a, key)
            except Exception as e:
                print(f"  ! 좌표 찾기 실패 {a}: {e}")
                continue
            if not g:
                print(f"  좌표 못 찾음: {a}")
                continue
            geo[a] = g
        n["geo"] = geo[a]
    GEO_CACHE.write_text(json.dumps(geo, ensure_ascii=False), encoding="utf-8")
    print(f"좌표: {sum(1 for n in notices if n.get('geo'))}건 / 주소 있는 공고 {sum(1 for n in notices if n['addresses'])}건")


def main():
    load_env()
    kb = Kbid(os.environ["KBID_ID"], os.environ["KBID_PW"])
    for name, query in kb.login():
        print(f"로그인 완료, 탭 「{name}」 조건: {query}")

    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    today = datetime.now(KST).date()
    notices, seen = [], {}
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
            if info and "dates" not in info:
                # 일정 항목이 생기기 전에 저장한 공고 — 상세 화면만 다시 받아 일정을 채운다
                det = kb.detail(row["bid_no"], row["bid_seq"])
                body = file_text("body.html", det["body_html"].encode()) if det["body_html"] else ""
                info["dates"] = extract_dates(det["fields"], body)
            if not info:
                det = kb.detail(row["bid_no"], row["bid_seq"])
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
                # 주소를 찾은 공고만 저장해 둔다 (못 찾은 건 다음 날 다시 시도 — 정정공고로 첨부가 바뀔 수 있음)
                if found:
                    cache[key] = info
                print(f"  {row['title'][:40]} → {info['addresses'] or '주소 못 찾음'}")
            seen[key] = {
                "date": day.isoformat(), "tabs": [tab],
                "title": row["title"], "agency": row["agency"], "kind": row["kind"],
                "region": row["region"], **info,
            }
            notices.append(seen[key])

    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
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
