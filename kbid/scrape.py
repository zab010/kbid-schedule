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
        r = self.s.get(urljoin(BASE, url), timeout=60, **kw)
        r.raise_for_status()
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
                 for a in soup.select("#bid_inner a[href*='fileUpload.do'], #bid_inner a[href*='g2b.go.kr/fs']")]
        body = soup.select_one("div.gongo_detail")
        return {"fields": fields, "files": files, "body_html": str(body) if body else ""}

    def download(self, url):
        time.sleep(PAUSE)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=120)
        r.raise_for_status()
        return r.content
