"""공고 원문(첨부파일·본문)에서 실제 공사 현장 주소를 찾아낸다."""
import io
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

# 현장 주소 앞에 붙는 항목 이름. 앞쪽일수록 우선.
SITE_KEYS = [
    "공사현장", "현장위치", "현장주소", "현장소재지", "공사위치", "공사장소", "공사장위치",
    "시공위치", "시공장소", "건설위치", "사업위치", "사업장소", "사업대상지", "사업지",
    "대상지", "설치장소", "설치위치", "납품장소", "소재지", "현장", "위치",
]
# "현장설명", "현장대리인"처럼 주소가 아닌 항목
NOT_SITE = re.compile(r"^(?:설명|대리인|확인|방문|여건|관리|조건|사무소|인력|근로자|참석|기술인|배치|소장|안전)")
# 여러 현장을 표로 나열할 때 쓰는 열 머리글
TABLE_HEADERS = {"대상주소", "현장주소", "공사위치", "현장위치", "소재지", "주소", "설치장소", "위치"}
SECTION = re.compile(r"^(?:[가-하]\.|\d+(?:\.\d+)*\.|-\s|※|\*)")
SIDO = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
        "충북", "충남", "충청", "전북", "전남", "전라", "경북", "경남", "경상", "제주")


NOT_ADDR = re.compile(r"합니다|하며|하여야|해야|경우|계약|법률|등기|입찰|제출|지급|신고|판결|참가|자격|서류|교체를|작업|기준|협의")


def _looks_like_address(s):
    """시·도 이름이나 '○○시/군/구'로 시작하는 주소 모양만 인정한다."""
    if len(s) < 4 or len(s) > 120 or NOT_ADDR.search(s):
        return False
    first = s.split()[0]
    return first.startswith(SIDO) or bool(re.fullmatch(r"[가-힣]{1,6}(?:시|군|구)", first))


def _clean(s):
    s = re.sub(r"\s+", " ", s).strip(" .,:;·-※○◦ㅇ□■▶►•")
    # 뒤에 딸려 온 다른 항목(예: "공사기간 : …") 잘라내기
    s = re.split(r"\s(?:공\s*사\s*기\s*간|공사개요|공사규모|공사내용|사업기간|착공|준공|계약방법|추정가격|기초금액|입찰|2\.|나\.|\d\)\s)", s)[0]
    return s.strip(" .,:;")


def _score(addr, key):
    sc = 0
    if addr.startswith(SIDO):
        sc += 3
    if re.search(r"\d", addr):
        sc += 2
    if "일원" in addr or "일대" in addr or "번지" in addr:
        sc += 1
    sc += max(0, 6 - SITE_KEYS.index(key) // 3) if key in SITE_KEYS else 0
    return sc


def find_site_addresses(text):
    """본문에서 현장 주소 후보를 점수순으로 돌려준다. [(주소, 근거항목)]"""
    text = text.replace("\xa0", " ").replace("\u3000", " ")
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    found = {}
    for i, line in enumerate(lines):
        # "공 사 위 치"처럼 글자 사이에 띄어쓰기가 있는 표 머리글도 잡도록 공백 없는 사본에서 찾는다
        squeezed = line.replace(" ", "")
        if squeezed in TABLE_HEADERS:
            # 표의 주소 열: 다음 절이 시작될 때까지 주소 모양의 칸을 모두 모은다
            rows = []
            for x in lines[i + 1:i + 120]:
                if SECTION.match(x):
                    break
                c = _clean(x)
                if _looks_like_address(c):
                    rows.append(c)
            if len(rows) >= 2:
                for c in rows:
                    found.setdefault(c, (_score(c, "현장주소"), squeezed))
                continue
        for key in SITE_KEYS:
            pos = squeezed.find(key)
            if pos < 0 or pos > 12:
                continue
            if NOT_SITE.match(squeezed[pos + len(key):]):
                continue
            # 원래 줄에서 항목 이름 다음 위치 찾기
            n, j = 0, 0
            while j < len(line) and n < pos + len(key):
                if line[j] != " ":
                    n += 1
                j += 1
            rest = _clean(re.sub(r"^\s*[:：\-]?\s*", "", line[j:]))
            cands = [rest] if rest else []
            # 표에서는 주소가 다음 칸(다음 줄)에 있다
            if not rest or not _looks_like_address(rest):
                for x in lines[i + 1:i + 3]:
                    if any(x.replace(" ", "").startswith(k) for k in SITE_KEYS):
                        break  # 다음 줄이 다른 항목이면 거기서 멈춘다
                    cands.append(_clean(x))
            for c in cands:
                if _looks_like_address(c):
                    sc = _score(c, key)
                    if c not in found or found[c][0] < sc:
                        found[c] = (sc, key)
                    break
            break
    ranked = sorted(found.items(), key=lambda kv: -kv[1][0])
    # 다른 후보에 통째로 들어 있는 짧은 후보는 뺀다
    out = []
    for addr, (sc, key) in ranked:
        if any(addr in o for o, _ in out):
            continue
        out.append((addr, key))
    return out


# ---------- 첨부파일 → 글자 ----------

def _hwp_text(data):
    # hwp5txt는 표 안의 글자를 빼먹으므로 XML로 풀어서 문단·표 칸마다 줄을 나눈다
    import html
    with tempfile.NamedTemporaryFile(suffix=".hwp") as f:
        f.write(data)
        f.flush()
        r = subprocess.run(["hwp5proc", "xml", f.name], capture_output=True, timeout=180)
    xml = r.stdout.decode("utf-8", "ignore")
    xml = re.sub(r"</Paragraph>|</TableCell>", "\n", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def _hwpx_text(data):
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml", n)):
            xml = z.read(name).decode("utf-8", "ignore")
            # 문단 끝과 표 칸 끝을 줄바꿈으로
            xml = re.sub(r"</hp:p>|</hp:tc>", "\n", xml)
            xml = re.sub(r"<[^>]+>", "", xml)
            out.append(xml)
    return "\n".join(out)


def _pdf_text(data):
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in r.pages[:30])


def _docx_text(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>|</w:tc>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _html_text(data):
    from bs4 import BeautifulSoup
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            html = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        html = data.decode("utf-8", "ignore")
    soup = BeautifulSoup(html, "html.parser")
    for td in soup.find_all(["td", "th", "br", "p", "div", "li"]):
        td.append("\n")
    return soup.get_text()


def file_text(name, data):
    """파일 이름과 내용으로 글자를 뽑는다. 못 읽으면 빈 문자열."""
    ext = Path(name.lower()).suffix
    try:
        if ext == ".hwp" or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            return _hwp_text(data)
        if ext == ".hwpx" or (data[:2] == b"PK" and b"Contents/section" in data[:4000]):
            return _hwpx_text(data)
        if ext == ".pdf" or data[:4] == b"%PDF":
            return _pdf_text(data)
        if ext == ".docx":
            return _docx_text(data)
        if ext in (".htm", ".html", ".txt") or data.lstrip()[:1] == b"<":
            return _html_text(data)
    except Exception as e:  # 깨진 파일은 건너뛴다
        print(f"  ! {name} 읽기 실패: {e}")
    return ""
