"""원문에서 현장 주소를 못 찾은 공고의 위치를 공고 제목·공고기관·수요기관·발주기관 이름으로 추정한다.

순서: 해외 공고 → 제목·기관 이름 속 시·군 지명 → 기관 이름을 오픈스트리트맵에서 검색 → 시·도만.
공고기관이 '조달청 ○○지방조달청'이면 이름은 현장과 무관하지만, 맡은 지역(○○)을 시·도 힌트로 쓴다.
제목의 [경기] 같은 지역 표시나 KBID 목록 지역이 있으면 그와 어긋나는 결과는 버린다."""
import re

SIDO_FULL = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시", "광주": "광주광역시",
    "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시", "경기": "경기도", "강원": "강원특별자치도",
    "충북": "충청북도", "충남": "충청남도", "전북": "전북특별자치도", "전남": "전라남도",
    "경북": "경상북도", "경남": "경상남도", "제주": "제주특별자치도",
    "광주·전남": "전라남도",  # 2026 통합 지역 표기 — 지도 검색에는 옛 이름을 쓴다
}
# 주소·지역 글자 → 짧은 시·도 이름 (앞에서부터 먼저 맞는 것)
SIDO_PREFIX = [
    ("전남광주", "광주·전남"), ("서울", "서울"), ("부산", "부산"), ("대구", "대구"), ("인천", "인천"), ("광주광역", "광주"),
    ("대전", "대전"), ("울산", "울산"), ("세종", "세종"), ("경기", "경기"), ("강원", "강원"),
    ("충청북", "충북"), ("충북", "충북"), ("충청남", "충남"), ("충남", "충남"),
    ("전라북", "전북"), ("전북", "전북"), ("전라남", "전남"), ("전남", "전남"),
    ("경상북", "경북"), ("경북", "경북"), ("경상남", "경남"), ("경남", "경남"), ("제주", "제주"), ("광주", "광주"),
]
SIGUN = {
    "경기": "수원 성남 의정부 안양 부천 광명 평택 동두천 안산 고양 과천 구리 남양주 오산 시흥 군포 의왕 하남 용인 "
            "파주 이천 안성 김포 화성 광주 양주 포천 여주 연천 가평 양평",
    "강원": "춘천 원주 강릉 동해 태백 속초 삼척 홍천 횡성 영월 평창 정선 철원 화천 양구 인제 고성 양양",
    "충북": "청주 충주 제천 보은 옥천 영동 증평 진천 괴산 음성 단양",
    "충남": "천안 공주 보령 아산 서산 논산 계룡 당진 금산 부여 서천 청양 홍성 예산 태안",
    "전북": "전주 군산 익산 정읍 남원 김제 완주 진안 무주 장수 임실 순창 고창 부안",
    "전남": "목포 여수 순천 나주 광양 담양 곡성 구례 고흥 보성 화순 장흥 강진 해남 영암 무안 함평 영광 장성 완도 진도 신안",
    "경북": "포항 경주 김천 안동 구미 영주 영천 상주 문경 경산 의성 청송 영양 영덕 청도 고령 성주 칠곡 예천 봉화 울진 울릉",
    "경남": "창원 진주 통영 사천 김해 밀양 거제 양산 의령 함안 창녕 고성 남해 하동 산청 함양 거창 합천",
    "제주": "제주 서귀포",
    "대구": "군위 달성", "부산": "기장", "인천": "강화 옹진", "울산": "울주",
}
_GUN = {"연천", "가평", "양평", "홍천", "횡성", "영월", "평창", "정선", "철원", "화천", "양구", "인제", "고성", "양양",
        "보은", "옥천", "영동", "증평", "진천", "괴산", "음성", "단양", "금산", "부여", "서천", "청양", "홍성", "예산", "태안",
        "완주", "진안", "무주", "장수", "임실", "순창", "고창", "부안", "담양", "곡성", "구례", "고흥", "보성", "화순", "장흥",
        "강진", "해남", "영암", "무안", "함평", "영광", "장성", "완도", "진도", "신안", "의성", "청송", "영양", "영덕", "청도",
        "고령", "성주", "칠곡", "예천", "봉화", "울진", "울릉", "의령", "함안", "창녕", "남해", "하동", "산청", "함양", "거창",
        "합천", "군위", "달성", "기장", "강화", "옹진", "울주"}
# 이름만 쓰여도 기관·지점 이름이면 지명으로 본다 (예: '진주지청', '거제영업소')
_ORG_TAIL = r"(?:시청|군청|교육지원청|지청|지사|지점|영업소|사무소|출장소|센터|본부|공장|캠퍼스|역)"
# 보통 낱말로도 흔히 쓰이는 지명 — '예산시'·'강화군'·'양산지사'처럼 뒤에 시·군·기관이 붙을 때만 지명으로 본다
_AMBIG = set("예산 강화 양산 달성 전주 상주 영양 음성 수원 장성 구리 경주 기장 보은 진주 동해 부여 장수 고령 영광 성주 "
             "진도 청도 신안 인제 광주 고성 보성 영동 양주 아산 사천 남해 광명 금산 서천 함평 장흥 화순".split())
_NAMES = sorted({n for v in SIGUN.values() for n in v.split()}, key=len, reverse=True)
_SIDO2 = "서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주"
# 앞이 한글이 아니거나 시·도 이름일 때 (예: '파주교하', '부천 중동역', '강원인제', '(영암군)')
_SIGUN_RE = re.compile(rf"(?:(?<![가-힣])|(?<={_SIDO2}|국립))({'|'.join(_NAMES)})(?!향대)(시|군|{_ORG_TAIL})?")
_SIDO_RE = re.compile(r"(?<![가-힣])(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충청북|충청남|전라북|전라남|"
                      r"경상북|경상남|충북|충남|전북|전남|경북|경남|제주)"
                      r"(특별시|광역시|특별자치시|특별자치도|도|시)?")
# 전국에 지사가 있는 기관 — 지점 이름 없이 기관 이름만으로는 현장 위치를 알 수 없다
_NATIONWIDE = re.compile(r"^(?:한국토지주택공사|LH|한국전력공사|한전KPS|한국수자원공사|한국도로공사|한국철도공사|코레일.*|국가철도공단|"
                         r"공무원연금공단|국민연금공단|국민건강보험공단|근로복지공단|중소기업은행|IBK기업은행|국민은행|농협.*|"
                         r"한국농어촌공사|한국가스공사|한국환경공단|한국자산관리공사|한국산업단지공단|한국국토정보공사|"
                         r"방위사업청|국방부.*|국군.*|외교부|대한무역투자진흥공사|KOTRA|한국인프라관리|한국능률협회컨설팅)$")
FOREIGN = re.compile(r"해외|국외|두바이|UAE|미국|마이애미|라스베이거스|뉴욕|독일|뒤셀도르프|프랑크푸르트|일본|도쿄|오사카|"
                     r"중국|상하이|베이징|홍콩|대만|베트남|태국|싱가포르|인도네시아|말레이시아|필리핀|인도|사우디|카타르|"
                     r"프랑스|파리|영국|런던|이탈리아|밀라노|스페인|바르셀로나|네덜란드|덴마크|스웨덴|캐나다|멕시코|브라질|"
                     r"코스타리카|알제리|이집트|케냐|아제르바이잔|카자흐스탄|우즈베키스탄|몽골|호주|CES\b|MWC\b|한국관|단체관")
_ORG_JUNK = re.compile(r"\(\s*(?:주|재|사|유|합)\s*\)|주식회사|유한회사|재단법인|사단법인|사회복지법인|학교법인|의료법인|"
                       r"\s+")
_GENERIC = re.compile(r"^(?:은행|외교부|조달청|.{1,3}부|.{1,2}청|.{1,2}공사|.{1,2}조합)$")


def sido_of(text):
    """주소처럼 시·도로 시작하는 글자 → 짧은 시·도 이름."""
    t = (text or "").strip()
    for k, v in SIDO_PREFIX:
        if t.startswith(k):
            return v
    return ""


def brackets(title):
    return re.findall(r"\[([^\]]+)\]", title or "")


def _sido_in(text):
    for m in _SIDO_RE.finditer(text or ""):
        rest = text[m.end():m.end() + 2]
        # '광주시'는 경기 광주일 수 있고, '경기장'·'세종대왕' 같은 낱말은 지역이 아니다
        if m.group(1) == "광주" and m.group(2) in ("시", None):
            continue
        if not m.group(2) and re.match(r"장|침|대왕|문화|대로", rest):
            continue
        return sido_of(m.group(1))
    return ""


def _orgs(n):
    """(구분, 기관 이름) — 수요기관·발주기관·공고기관. 계약만 맡은 조달청 이름(예: '조달청 인천지방조달청')은 현장과 무관해 뺀다."""
    out = []
    for kind, name in (("수요기관", n.get("demand", "")), ("발주기관", n.get("orderer", "")), ("공고기관", n["agency"])):
        if name and not name.startswith("조달청") and name not in [o for _, o in out]:
            out.append((kind, name))
    return out


def _texts(n):
    return [n["title"]] + [_ORG_JUNK.sub(" ", name).strip() for _, name in _orgs(n)]


def pps_sido(n):
    """공고기관 '조달청 대전지방조달청' → '대전' (그 지방청이 맡은 지역)."""
    m = re.match(r"조달청\s*(\S+?)지방조달청", n["agency"] or "")
    return sido_of(m.group(1)) if m else ""


def hint_sido(n):
    """제목 [지역] 표시 → 제목·기관의 시·도 이름 → KBID 목록 지역 순으로 시·도 힌트."""
    for b in brackets(n["title"]):
        s = sido_of(b.strip())
        if s:
            return s
    for t in _texts(n):
        s = _sido_in(t)
        if s:
            return s
    return sido_of(n.get("region", ""))


def sigun_in(n, hint):
    """제목·수요기관·발주처에서 시·군 지명 → (시·도, '거제시')."""
    strong = hint and any(sido_of(b) == hint for b in brackets(n["title"]))
    for t in _texts(n):
        for m in _SIGUN_RE.finditer(t):
            name, tail = m.group(1), m.group(2)
            glued = m.start() >= 2 and t[m.start() - 2:m.start()] in _SIDO2.split("|")
            if not tail and name in _AMBIG and not glued:
                continue
            sidos = [s for s, v in SIGUN.items() if name in v.split()]
            if hint in sidos:
                sidos = [hint]
            elif strong and tail not in ("시", "군"):
                continue  # 제목의 [지역] 표시와 다른 곳의 '○○지사' 같은 건 믿지 않는다
            unit = "군" if name in _GUN else "시"
            if name in ("광주", "고성") and len(sidos) > 1 and tail not in ("시", "군"):
                continue
            if name == "광주" and tail == "시":
                sidos = ["경기"]
            return sidos[0], name + unit
    return None


def org_names(n):
    """지도에서 찾아볼 (구분, 기관 이름)."""
    out = []
    for kind, name in _orgs(n):
        q = _ORG_JUNK.sub(" ", name).strip()
        q = re.sub(r"\s+", " ", q)
        if len(q.replace(" ", "")) >= 3 and not _GENERIC.match(q) and not _NATIONWIDE.match(q) and q not in [o for _, o in out]:
            out.append((kind, q))
    return out


def guess(n, search):
    """search(q) → {lat, lon, sido, text} 또는 None (오픈스트리트맵 장소 검색, 캐시는 부르는 쪽에서).
    돌려주는 값: {'text': 추정 위치, 'how': 근거, 'sido': 시·도, 'geo': 좌표 또는 None}"""
    blob = " ".join(_texts(n))
    hint = hint_sido(n)
    m = FOREIGN.search(blob)
    if m and not any(sido_of(b) for b in brackets(n["title"])):
        return {"text": "해외", "how": f"제목·기관의 '{m.group(0)}'", "sido": "해외", "geo": None}
    sg = sigun_in(n, hint)
    if sg:
        q = f"{SIDO_FULL[sg[0]]} {sg[1]}"
        hit = search(q)
        return {"text": q, "how": f"제목·기관 이름의 지명 '{sg[1][:-1]}'", "sido": sg[0],
                "geo": {"lat": hit["lat"], "lon": hit["lon"], "q": q, "level": "guess"} if hit else None}
    for kind, org in org_names(n):
        for q in ([f"{org} {SIDO_FULL[hint]}"] if hint else []) + [org]:
            hit = search(q)
            if hit and (not hint or hit["sido"] == hint):
                return {"text": hit["text"], "how": f"{kind} '{org}' 위치", "sido": hit["sido"],
                        "geo": {"lat": hit["lat"], "lon": hit["lon"], "q": hit["text"], "level": "guess"}}
    if hint:
        how = "제목의 지역 표시" if any(sido_of(b) for b in brackets(n["title"])) else (
            "제목·기관 이름" if _sido_in(blob) else "KBID 공고 지역")
        return {"text": SIDO_FULL[hint], "how": how, "sido": hint, "geo": None}
    pps = pps_sido(n)  # 가장 약한 근거라 다른 단서를 거르는 데는 쓰지 않는다
    if pps:
        return {"text": SIDO_FULL[pps], "how": f"공고기관 '{n['agency']}' 관할 지역", "sido": pps, "geo": None}
    return None
