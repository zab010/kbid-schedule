"""케이비드 맞춤스케줄러에서 공고 목록과 상세 정보를 가져온다."""
import re
import time
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.kbid.co.kr"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
PAUSE = 0.7  # 요청 사이 쉬는 시간(초) — 사이트에 부담을 주지 않도록


class Kbid:
    def __init__(self, user, pw):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.user, self.pw = user, pw
        self.tabs = []  # [(탭 이름, 조건 문자열)]

    def _get(self, url, **kw):
        time.sleep(PAUSE)
        # 서버가 가끔 연결을 끊는다 — 잠시 쉬었다가 다시 시도
        for wait in (10, 30, 90, None):
            try:
                r = self.s.get(urljoin(BASE, url), timeout=60, **kw)
                r.raise_for_status()
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                if wait is None:
                    raise
                print(f"  연결 오류, {wait}초 뒤 다시 시도: {e}")
                time.sleep(wait)
        r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
        return r

    def login(self):
        self._get("/first/index_first.htm")
        self.s.post(BASE + "/member/SslUp.php", timeout=60,
                    headers={"Referer": BASE + "/first/index_first.htm"},
                    data={"MemID": self.user, "MemPW": self.pw, "firstLogin": "1",
                          "SSL_Login": "1", "Kpath": "Y"})
        page = self._get("/mypage/IndustryTypesCalendar.htm").text
        if "로그아웃" not in page:
            raise RuntimeError("케이비드 로그인 실패 — 아이디/비밀번호 또는 이용기간을 확인하세요")
        # 맞춤스케줄러 탭(대전 권역·전국 등). 이름이 '미설정'인 빈 탭은 건너뛴다
        tabs = re.findall(r'IndustryTypesCalendar\.htm\?Mtype=(\d+)">\s*([^<]+?)\s*</a>', page)
        for mtype, name in tabs:
            if name == "미설정":
                continue
            if mtype != "1":
                page = self._get(f"/mypage/IndustryTypesCalendar.htm?Mtype={mtype}").text
            # 탭의 맞춤 조건(업종·지역)은 스케줄러 화면의 스크립트에 들어 있다
            m = re.search(r"industryTypesList\.php.*?'(&bidKind=[^']*)'", page, re.S)
            if m:
                self.tabs.append((name, m.group(1)))
        if not self.tabs:
            raise RuntimeError("맞춤스케줄러 조건을 찾지 못했습니다 (사이트 구조 변경?)")
        return self.tabs

    def day_list(self, day, query, order="FinishDTime"):
        """그날(정렬 기준 날짜) 공고 목록."""
        out, page = [], 1
        while True:
            url = (f"/mypage/industryTypesList.php?setYear={day.year}&setMonth={day.month:02d}"
                   f"&setDay={day.day:02d}&page={page}&state=1&searchDate={order}{query}")
            soup = BeautifulSoup(self._get(url).text, "html.parser")
            for li in soup.select("#cal-list li.list-item"):
                a = li.select_one(".ln-subject a")
                if not a:
                    continue
                q = parse_qs(urlparse(a["href"]).query)
                cell = lambda c: (li.select_one(c).get_text(" ", strip=True) if li.select_one(c) else "")
                out.append({
                    "bid_no": q["BidNo"][0], "bid_seq": q.get("BidNoSeq", ["0"])[0],
                    "title": a.get_text(" ", strip=True),
                    "agency": cell(".ln-org1"), "kind": cell(".ln-org"), "region": cell(".ln-area").strip("[]"),
                })
            pages = [int(x) for x in re.findall(r"[?&]page=(\d+)", str(soup.select_one(".paging") or ""))]
            if not pages or page >= max(pages):
                return out
            page += 1

    def detail(self, bid_no, bid_seq):
        r = self._get(f"/mypage/mypage_bid_contents.htm?BidNo={bid_no}&BidNoSeq={bid_seq}&chkCode=Y")
        soup = BeautifulSoup(r.text, "html.parser")
        fields = {}
        for th in soup.select("#bid_inner th"):
            td = th.find_next_sibling("td")
            if not td:
                continue
            k = th.get_text(" ", strip=True)
            v = re.sub(r"\s*투찰하기\s*$", "", td.get_text(" ", strip=True))
            if re.search(r"\d|[가-힣]{2}", v) and k not in fields:
                fields[k] = v
        files = [{"name": a.get_text(" ", strip=True), "url": a["href"]}
                 for a in soup.select("#bid_inner a[href*='fileUpload.do'], #bid_inner a[href*='g2b.go.kr/fs'], "
                                      "#bid_inner a[href*='g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do']")]
        body = soup.select_one("div.gongo_detail")
        return {"fields": fields, "files": files, "body_html": str(body) if body else "",
                "origin": origin_link(soup, r.text)}

    def download(self, url):
        time.sleep(PAUSE)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=120)
        r.raise_for_status()
        return r.content


G2B_NO = re.compile(r"^(R\d{2}[A-Z]{2}\d{8})-(\d{3})$")
G2B_URL = "https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo={}&bidPbancOrd={}"


def g2b_link(no):
    """나라장터 공고번호(R26BK01809536-000) → 나라장터 공고 상세 공개 주소."""
    m = G2B_NO.match(no or "")
    return G2B_URL.format(m[1], m[2]) if m else ""


def clean_origin(o):
    """원문 글에 붙어 있던 글자가 주소에 섞인 경우(http://www.k-apt.go.kr로)를 다듬는다."""
    if not o or not o.get("url"):
        return {}
    u = urlparse(o["url"])
    host = re.match(r"[A-Za-z0-9.\-:]*", u.netloc)[0]
    if host != u.netloc:
        return {"url": f"{u.scheme}://{host}/", "kind": "site"} if "." in host else {}
    return o


def origin_link(soup, html):
    """발주처 쪽 공고 원문 주소 {"url", "kind"} — KBID 주소는 쓰지 않는다.
    kind "notice" = 그 공고 화면, "site" = 공고가 올라온 발주처(입찰) 사이트 첫 화면.
    1) '[공고원문 열기]' 링크(K-apt 등) 2) 나라장터 공고 → KBID '발주처 원문' 버튼과 같은 나라장터 주소
    3) 공고기관 이름에 걸린 발주처 사이트 링크 (주소에 검색어가 있으면 그 공고 화면)"""
    for a in soup.select("#bid_inner a[href^='http']"):
        if "공고원문" in a.get_text() and "kbid" not in a["href"]:
            return {"url": a["href"], "kind": "notice"}
    m = re.search(r"G2b_Lnk1\('G2B_\w+?_Notice_([A-Z0-9]+)-(\d+)'", html)
    if m:
        return {"url": G2B_URL.format(m[1], m[2]), "kind": "notice"}
    for a in soup.select("#bid_inner a[href^='http']"):
        u = urlparse(a["href"])
        if (not a.get_text(strip=True) or "kbid" in u.netloc
                or re.search(r"download|fileUpload|FileDown|dnldFile", a["href"], re.I)):
            continue
        # 첫 번째 글자 있는 바깥 링크 = 공고기관 줄의 발주처 사이트
        return clean_origin({"url": a["href"], "kind": "notice" if u.query else "site"})
    return {}
