"""공고 상세 항목과 공고문 본문에서 입찰 일정(현장설명·참가신청마감·입찰개시·투찰마감·개찰)을 찾는다."""
import re

# 사이트에 보이는 이름 → KBID 상세 화면에서 같은 뜻으로 쓰이는 항목 이름들 (앞의 것이 우선)
DATE_FIELDS = {
    "현장설명일": ["현장설명일", "현장설명일시", "현설일시", "현장설명회일시"],
    "참가신청마감일": ["참가신청마감일", "참가신청마감일시", "참가등록마감일", "입찰참가신청마감일시"],
    "입찰개시일": ["입찰개시일", "입찰개시일시", "입찰서접수개시일시"],
    "투찰마감일시": ["투찰마감일시", "투찰마감일", "입찰마감일시", "입찰서접수마감일시", "입찰서 제출 마감일"],
    "입찰(개찰)일시": ["입찰(개찰) 일시", "입찰(개찰)일", "개찰일시"],
}

_DT = re.compile(r"(20\d\d)\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*일?\.?"
                 r"(?:\s*\([^)]{1,3}\))?(?:\s*(?:오전|오후)?\s*(\d{1,2})\s*[:시]\s*(\d{2})?)?")


def norm(v):
    """'2026/09/30 10:00', '2026-10-02 18:00:00' 같은 값을 '2026-09-30 10:00' 으로. 날짜가 없으면 ''."""
    m = _DT.search(v or "")
    if not m or m.group(1) == "0000":
        return ""
    y, mo, d, h, mi = m.groups()
    out = f"{y}-{int(mo):02d}-{int(d):02d}"
    if h is not None:
        hh = int(h)
        if "오후" in m.group(0) and hh < 12:
            hh += 12
        out += f" {hh:02d}:{int(mi or 0):02d}"
    return out


# 공고문 본문: '현장설명 : 2026. 10. 5.(월) 10:00' → 날짜, '현장설명을 생략…/실시하지 아니하며/별도의 현장설명이 없으므로' → 없음
# '현장설명서'(서류 이름)는 건너뛴다
_SITE_VISIT = re.compile(r"현장\s*설명(?!\s*서)")
_NO_VISIT = re.compile(r"없|생략|미실시|실시하지|하지\s*않|갈음")


def site_visit_from_text(text):
    found_none = False
    for m in _SITE_VISIT.finditer(text or ""):
        tail = text[m.end():m.end() + 80]
        no = _NO_VISIT.search(tail)
        d = _DT.search(tail)
        if d and (not no or d.start() < no.start()):
            v = norm(d.group(0))
            if v:
                return v
        # '별도의 현장설명이 없으므로'처럼 앞에 부정어가 오는 경우도 본다
        if no and no.start() < 30 or re.search(r"별도의?\s*$", text[max(0, m.start() - 8):m.start()]):
            found_none = True
    return "없음" if found_none else ""


def extract_dates(fields, *texts):
    """fields = KBID 상세 항목, texts = 공고문 본문·첨부 글자 (현장설명일을 찾을 때만 쓴다)."""
    out = {}
    for label, names in DATE_FIELDS.items():
        out[label] = next((v for v in (norm(fields.get(n, "")) for n in names) if v), "")
    if not out["현장설명일"]:
        if fields.get("현장설명회실시유무", "").strip() == "없음":
            out["현장설명일"] = "없음"
        else:
            out["현장설명일"] = next((v for v in map(site_visit_from_text, texts) if v), "")
    return out
