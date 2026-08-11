# -*- coding: utf-8 -*-
"""
공동주택가격 조회

브이월드 국가중점데이터(NED) API 사용.
공동주택가격속성조회: https://api.vworld.kr/ned/data/getApartHousingPriceAttr

※ 실제 응답 구조를 호출로 확인해서 반영함(2026-07 기준).
  응답: {"apartHousingPrices": {"field": [ ... ]}}
  주요 필드:
    aphusNm   단지명(예: "은마")   dongNm 동   hoNm 호
    prvuseAr  전용면적(㎡)          pblntfPc 공동주택가격(원)
    stdrYear  기준연도             floorNm 층
  확인된 동작:
    - dongNm / hoNm 를 '요청 파라미터'로 넘기면 서버가 해당 동/호만 반환한다.
    - stdrYear 를 넘기면 해당 연도만 반환한다(안 넘기면 과거~현재 전부).
    - 동일 세대가 중복 반환될 수 있어 중복 제거가 필요하다.
    - numOfRows 는 최대 1000. 그 이상이면 빈 응답이 오므로 페이징으로 수집한다.
    - 공동주택이 아닌 PNU면 apartHousingPrices 키 없이 totalCount:"0" 이 온다.
"""

import re
import datetime
import requests
from config import VWORLD_API_KEY, VWORLD_DOMAIN

APT_PRICE_URL = "https://api.vworld.kr/ned/data/getApartHousingPriceAttr"
MAX_ROWS = 1000


def _digits(s: str | None) -> str:
    """'27동' -> '27', '1401호' -> '1401'."""
    if s is None:
        return ""
    return re.sub(r"\D", "", str(s))


def _norm_dong(s: str | None) -> str | None:
    """
    동 라벨 정규화. 숫자 동('27동'->'27')과 한글 동('가동'/'제가동'->'가') 모두 지원.
    공동주택가격 API 의 dongNm 은 접미사 '동' 없이 '가'/'27' 처럼 저장돼 있어 그 형식에 맞춘다.
    """
    if s is None:
        return None
    t = re.sub(r"^제\s*", "", str(s).strip())   # 앞 '제' 제거
    t = re.sub(r"\s*동$", "", t).strip()         # 뒤 '동' 제거
    return t or None


def _dong_sort_key(dong: str | None):
    """동 정렬키. 숫자 동은 숫자순, 한글 동('가','나'…)은 글자순으로 정렬."""
    label = _norm_dong(dong) or ""
    if label.isdigit():
        return (0, int(label), "")
    return (1, 0, label)


def _query_page(pnu: str, dong: str | None, ho: str | None,
                year: str | None, page: int) -> list[dict]:
    params = {
        "key": VWORLD_API_KEY,
        "domain": VWORLD_DOMAIN,
        "pnu": pnu,
        "format": "json",
        "numOfRows": str(MAX_ROWS),
        "pageNo": str(page),
    }
    if dong:
        params["dongNm"] = dong
    if ho:
        params["hoNm"] = ho
    if year:
        params["stdrYear"] = year

    res = requests.get(APT_PRICE_URL, params=params, timeout=15)
    res.raise_for_status()
    node = res.json().get("apartHousingPrices")
    if isinstance(node, dict) and node.get("field"):
        return node["field"]
    return []


def _latest_year(pnu: str, dong: str | None = None, ho: str | None = None) -> str | None:
    """올해부터 역순으로 데이터가 존재하는 가장 최근 기준연도를 찾는다."""
    this_year = datetime.date.today().year
    for y in range(this_year, this_year - 8, -1):
        if _query_page(pnu, dong, ho, str(y), 1):
            return str(y)
    return None


def is_apartment(pnu: str) -> bool:
    """해당 PNU가 공동주택 단지인지(공동주택가격 데이터 존재 여부)."""
    return bool(_query_page(pnu, None, None, None, 1))


def apt_name(pnu: str) -> str | None:
    """공동주택이면 단지명(aphusNm)을, 아니면 None."""
    fld = _query_page(pnu, None, None, None, 1)
    return fld[0].get("aphusNm") if fld else None


def pnu_jibun(pnu: str) -> str:
    """PNU에서 '본번-부번' 지번 문자열을 만든다(부번 0이면 본번만)."""
    if len(pnu) != 19:
        return pnu
    bon, bu = int(pnu[11:15]), int(pnu[15:19])
    return f"{bon}-{bu}" if bu else str(bon)


def nearby_apt_candidates(pnu: str, span: int = 2) -> list[dict]:
    """
    여러 필지에 걸친 집합건물의 '예상 대표지번' 후보 목록.
    입력 PNU 필지에 공동주택 데이터가 없을 때, 같은 본번의 인접 부번(±span)을 훑어
    공동주택이 있는 필지를 찾는다. (span 은 주소의 '외 N필지' 개수로 주면 정확)

    반환: [{"pnu","jibun","name"}, ...]  (입력 부번에 가까운 순, 단지명 중복 제거)
    사용자가 이 중 하나를 골라 그 지번으로 재조회하도록 화면에 띄운다(자동 조회 안 함).
    """
    if len(pnu) != 19:
        return []
    head, bubun = pnu[:15], int(pnu[15:19])
    found: list[dict] = []
    seen: set[str] = set()
    for b in sorted(range(max(0, bubun - span), bubun + span + 1),
                    key=lambda x: (abs(x - bubun), x)):   # 가까운 부번 먼저
        if b == bubun:
            continue
        cp = head + str(b).zfill(4)
        nm = apt_name(cp)
        if nm and nm not in seen:
            seen.add(nm)
            found.append({"pnu": cp, "jibun": pnu_jibun(cp), "name": nm})
    return found


def _to_row(item: dict) -> dict:
    row = {
        "danji_name": item.get("aphusNm"),
        "dong": item.get("dongNm"),
        "ho": item.get("hoNm"),
        "floor": item.get("floorNm"),
        "prvuse_area": None,
        "price_yeondo": item.get("stdrYear"),
        "price": None,
    }
    try:
        row["prvuse_area"] = float(item.get("prvuseAr")) if item.get("prvuseAr") else None
    except (ValueError, TypeError):
        pass
    try:
        row["price"] = int(item.get("pblntfPc", 0))
    except (ValueError, TypeError):
        pass
    return row


def get_apt_info(pnu: str, dong: str | None = None, ho: str | None = None) -> list[dict]:
    """
    PNU(단지가 깔린 필지) + (선택)동/호로 공동주택가격을 조회한다.
    동/호는 '27동','1401호'처럼 넣어도 숫자만 추출해 사용한다.
    최신 기준연도만 남기고 중복을 제거해 세대별 리스트를 반환한다.

    반환: [{"danji_name","dong","ho","floor","prvuse_area","price_yeondo","price"}, ...]
    """
    tdong = _norm_dong(dong)          # 동 정규화 라벨 ('가'·'108')
    thod = _digits(ho) or None        # 호는 '숫자'로 매칭 → '비02'↔'02', 'B동 301'↔'301'
    # 서버(dongNm/hoNm) 필터는 단지마다 저장형식이 제각각이라 신뢰 불가
    # ('3'·'108동'·'가' / '101'·'비02'·'B동 301'). 전체를 받아 클라이언트측에서 매칭한다.

    year = _latest_year(pnu, None, None)
    if not year:
        return []

    # 최신연도 전 세대를 페이징으로 수집
    raw: list[dict] = []
    page = 1
    while True:
        chunk = _query_page(pnu, None, None, year, page)
        raw.extend(chunk)
        if len(chunk) < MAX_ROWS:
            break
        page += 1

    # 중복 제거 (동,호,면적,가격 기준)
    seen = set()
    rows = []
    for item in raw:
        row = _to_row(item)
        key = (row["dong"], row["ho"], row["prvuse_area"], row["price"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)

    # 동으로 좁히기 — 동이 '실제 필드'로 있을 때만(빈 동 단지는 동이 호 안에 섞여 있어 무시)
    if tdong:
        m = [r for r in rows if _norm_dong(r.get("dong")) == tdong]
        if m:
            rows = m
    # 호는 숫자로 매칭 (라벨/접두 무관)
    if thod:
        rows = [r for r in rows if _digits(r.get("ho")) == thod]

    rows.sort(key=lambda r: (_dong_sort_key(r.get("dong")), _digits(r.get("ho")).zfill(6)))
    return rows


def list_dong_ho(pnu: str) -> list[tuple[str, str]]:
    """단지 내 (동, 호) 목록(최신연도). 동/호 미입력 시 선택지 제공용."""
    return [(r["dong"], r["ho"]) for r in get_apt_info(pnu)]


def unit_dongs(rows: list[dict]) -> list[str]:
    """세대 목록에서 정규화된 '동 라벨'들을 정렬해 반환('101','가' 등, 접미사 '동' 없음).
    동이 없는 단지면 빈 리스트."""
    labels = {_norm_dong(r.get("dong")) for r in rows}
    labels.discard(None)
    return sorted(labels, key=lambda x: (0, int(x)) if str(x).isdigit() else (1, str(x)))


def unit_hos(rows: list[dict], dong: str | None = None) -> list[str]:
    """세대 목록에서 (선택한 동의) '호' 번호들을 숫자 오름차순으로 반환."""
    td = _norm_dong(dong) if dong else None
    hos = {_digits(r.get("ho")) for r in rows
           if td is None or _norm_dong(r.get("dong")) == td}
    hos.discard("")
    return sorted(hos, key=lambda x: int(x))


if __name__ == "__main__":
    apt_pnu = "1168010600103160000"  # 은마아파트
    print("공동주택 여부:", is_apartment(apt_pnu))
    for r in get_apt_info(apt_pnu, dong="27동", ho="1401호"):
        print(r)
