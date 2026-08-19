# -*- coding: utf-8 -*-
"""
국토교통부 실거래가(RTMS) 조회 — 공공데이터포털(data.go.kr) OpenAPI

공시가격(브이월드)과 '같은 필지'의 실제 거래가를 함께 보여주기 위한 보조 데이터.
KB시세 등 비공개/크롤링 소스 대신, 공식·무료·합법인 국토부 실거래가를 사용한다.

필요: config.DATA_GO_KR_API_KEY (data.go.kr '일반 인증키(Decoding)')
조회키:
  - LAWD_CD : 시군구 법정동코드 5자리 = PNU 앞 5자리
  - DEAL_YMD: 계약연월 YYYYMM (최근 N개월을 훑는다)

엔드포인트(2023~ 신규):
  - 아파트 매매       : /RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade
  - 연립다세대 매매   : /RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade
  - 단독/다가구 매매  : /RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade
  - 토지 매매         : /RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade

응답은 XML. <item> 아래 자식 태그를 dict 로 일반 파싱한 뒤 필요한 필드를 매핑한다
(엔드포인트마다 태그명이 조금씩 달라 일반 파싱이 안전하다).
"""

import datetime
import xml.etree.ElementTree as ET

import requests

from config import DATA_GO_KR_API_KEY, has_datago_key

BASE = "http://apis.data.go.kr/1613000"
ENDPOINTS = {
    "apt":  f"{BASE}/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
    "rh":   f"{BASE}/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
    "sh":   f"{BASE}/RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade",
    "land": f"{BASE}/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade",
}


class NoKeyError(RuntimeError):
    """공공데이터포털 인증키가 설정되지 않았을 때."""


def _lawd_cd(pnu: str) -> str | None:
    """PNU(19자리) 앞 5자리 = 시군구 법정동코드(LAWD_CD)."""
    if pnu and len(pnu) >= 5 and pnu[:5].isdigit():
        return pnu[:5]
    return None


def _recent_months(n: int) -> list[str]:
    """이번 달부터 과거로 n개월치 'YYYYMM' 목록."""
    today = datetime.date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def _get(text_or_tag) -> str:
    return (text_or_tag or "").strip()


def _parse_items(xml_text: str) -> list[dict]:
    """RTMS XML 응답에서 <item> 들을 {태그:텍스트} dict 목록으로 파싱."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    # 에러 코드 확인 (resultCode 00 = 정상)
    items = []
    for item in root.iter("item"):
        d = {}
        for child in list(item):
            d[child.tag.strip()] = _get(child.text)
        if d:
            items.append(d)
    return items


def _result_msg(xml_text: str) -> str | None:
    """정상(00)이 아니면 에러 메시지를 반환, 정상이면 None."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # 공공데이터포털은 키 오류 시 다른 형식(OpenAPI_ServiceResponse)을 주기도 함
        if "SERVICE" in (xml_text or "") or "KEY" in (xml_text or ""):
            return "인증키 오류이거나 활용신청이 승인되지 않았습니다."
        return None
    code = None
    for tag in ("resultCode", "returnReasonCode"):
        el = root.find(f".//{tag}")
        if el is not None and el.text:
            code = el.text.strip()
            break
    if code in (None, "00", "000"):
        return None
    msg = ""
    for tag in ("resultMsg", "returnAuthMsg", "errMsg"):
        el = root.find(f".//{tag}")
        if el is not None and el.text:
            msg = el.text.strip()
            break
    return msg or f"오류코드 {code}"


def _amount_won(s: str) -> int | None:
    """'12,345'(만원) → 123450000(원)."""
    s = (s or "").replace(",", "").strip()
    if not s.isdigit():
        return None
    return int(s) * 10000


def _to_float(s: str) -> float | None:
    try:
        return float((s or "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _query(kind: str, lawd: str, ymd: str) -> tuple[list[dict], str | None]:
    """엔드포인트 1개 · 1개월 조회 → (items, error_msg)."""
    params = {
        "serviceKey": DATA_GO_KR_API_KEY,
        "LAWD_CD": lawd,
        "DEAL_YMD": ymd,
        "numOfRows": "1000",
        "pageNo": "1",
    }
    res = requests.get(ENDPOINTS[kind], params=params, timeout=15)
    res.raise_for_status()
    err = _result_msg(res.text)
    if err:
        return [], err
    return _parse_items(res.text), None


def _row_common(d: dict) -> dict:
    """거래연월일·금액·층을 공통 매핑."""
    y = _get(d.get("dealYear"))
    m = _get(d.get("dealMonth"))
    day = _get(d.get("dealDay"))
    date = f"{y}.{int(m):02d}.{int(day):02d}" if (y and m and day) else (y or "")
    return {
        "date": date,
        "price": _amount_won(d.get("dealAmount")),
        "floor": _get(d.get("floor")) or None,
        "umd": _get(d.get("umdNm")) or None,
        "jibun": _get(d.get("jibun")) or None,
    }


def _name_match(a: str | None, b: str | None) -> bool:
    """단지명 느슨한 일치(공백 제거 후 부분 포함)."""
    if not a or not b:
        return False
    aa = a.replace(" ", "")
    bb = b.replace(" ", "")
    return aa in bb or bb in aa


def get_trades(result: dict, months: int = 12, limit: int = 15) -> dict:
    """
    조회 결과(address_router.lookup 의 반환 dict)에 대응하는 실거래가를 조회한다.

    반환:
      {
        "ok": bool,
        "message": str|None,          # 실패/안내 사유
        "kind": "apt"|"house"|"land"|None,
        "name": 단지명 or None,
        "trades": [ {date, price, area, floor, unit, jibun}, ... ]  # 최신순, 최대 limit
      }
    """
    if not has_datago_key():
        return {"ok": False, "kind": None, "name": None, "trades": [],
                "message": ("공공데이터포털 인증키가 없습니다.\n"
                            "data.go.kr에서 실거래가 활용신청 후 datago_key.txt에 키를 넣으세요.")}

    pnu = result.get("pnu")
    lawd = _lawd_cd(pnu)
    if not lawd:
        return {"ok": False, "kind": None, "name": None, "trades": [],
                "message": "지역코드를 확인할 수 없습니다."}

    sec = result.get("sections", {})
    # 대상 지번(단독/토지 매칭용): base_address 끝의 '본번-부번'
    import re
    mjib = re.search(r"(\d+(?:-\d+)?)\s*$", (result.get("base_address") or ""))
    target_jibun = mjib.group(1) if mjib else None

    # 유형 판별 + 매칭 대상
    apt = sec.get("apt") or {}
    apt_rows = apt.get("rows") or []
    if apt_rows and not apt.get("not_apt"):
        kind, name = "apt", (apt_rows[0].get("danji_name") or None)
        target_area = apt_rows[0].get("prvuse_area")
        kinds = ["apt", "rh"]                     # 아파트 + 연립다세대 둘 다 훑어 매칭
    elif (sec.get("house") or {}).get("price") is not None:
        kind, name, target_area = "house", None, None
        kinds = ["sh"]
    elif sec.get("land"):
        kind, name, target_area = "land", None, None
        kinds = ["land"]
    else:
        return {"ok": False, "kind": None, "name": None, "trades": [],
                "message": "실거래가를 조회할 유형이 없습니다."}

    trades: list[dict] = []
    err_msg = None
    try:
        for ymd in _recent_months(months):
            for k in kinds:
                items, err = _query(k, lawd, ymd)
                if err:
                    err_msg = err
                    continue
                for d in items:
                    row = _row_common(d)
                    if row["price"] is None:
                        continue
                    tname = (d.get("aptNm") or d.get("mhouseNm")
                             or d.get("offiNm") or "")
                    tarea = _to_float(d.get("excluUseAr") or d.get("totalFloorAr")
                                      or d.get("dealArea") or d.get("plottageAr"))
                    if kind == "apt":
                        if not _name_match(name, tname):
                            continue
                        # 전용면적이 비슷한 거래만(±0.5㎡)
                        if target_area and tarea and abs(tarea - target_area) > 0.5:
                            continue
                        unit = tname or name
                    elif kind == "house":
                        if target_jibun and row["jibun"] and row["jibun"] != target_jibun:
                            continue
                        unit = f"{row['umd'] or ''} {row['jibun'] or ''}".strip()
                    else:  # land
                        if target_jibun and row["jibun"] and row["jibun"] != target_jibun:
                            continue
                        unit = _get(d.get("jimok")) or "토지"
                    trades.append({
                        "date": row["date"], "price": row["price"],
                        "area": tarea, "floor": row["floor"], "unit": unit,
                        "jibun": row["jibun"],
                    })
    except requests.RequestException as e:
        if not trades:
            return {"ok": False, "kind": kind, "name": name, "trades": [],
                    "message": f"실거래가 조회 중 네트워크 오류: {e}"}

    # 최신순 정렬 후 상위 limit
    trades.sort(key=lambda t: t["date"], reverse=True)
    trades = trades[:limit]

    if not trades:
        msg = err_msg or ("최근 %d개월 내 매칭되는 실거래 내역이 없습니다." % months)
        return {"ok": True, "kind": kind, "name": name, "trades": [], "message": msg}
    return {"ok": True, "kind": kind, "name": name, "trades": trades, "message": None}


if __name__ == "__main__":
    import address_router
    r = address_router.lookup("서울특별시 강남구 대치동 316 27동 1401호")
    import json
    print(json.dumps(get_trades(r), ensure_ascii=False, indent=2))
