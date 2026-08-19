# -*- coding: utf-8 -*-
"""
조회 필지를 브라우저 지도에 표시 (VWorld 지도)

동작:
  1) 주소 → 좌표(경도/위도) 변환 (pnu_util.address_to_coord)
  2) VWorld WMTS 배경지도 + 지적도(연속지적) 오버레이 + 마커가 있는
     Leaflet HTML 을 생성
  3) 로컬 HTTP 서버(127.0.0.1)를 잠깐 띄우고 http://localhost:포트/ 로 브라우저를 연다
     - VWorld 인증키의 등록 도메인이 'localhost' 이면 Referer 가 일치해 타일이 정상 로드됨
     - 파일(file://)로 열면 도메인이 안 맞아 타일이 막힐 수 있어 로컬 서버 방식을 쓴다
  4) VWorld 타일이 막히는 환경을 대비해 OSM 대체 배경도 레이어 전환으로 제공(지도가 비지 않음)

발표/시연 포인트: 공시가격을 조회한 '바로 그 필지'를 지도 위에 지적경계와 함께 보여준다.
"""

import html
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pnu_util
from config import VWORLD_API_KEY, VWORLD_DOMAIN

# 띄운 로컬 서버들을 살려두기 위한 참조(데몬 스레드라 앱 종료 시 함께 종료)
_servers = []


def _map_html(lon: float, lat: float, label: str) -> str:
    key = VWORLD_API_KEY
    safe_label = html.escape(label or "")
    # 자바스크립트 문자열로 안전하게 주입
    js_label = json.dumps(safe_label, ensure_ascii=False)
    js_key = json.dumps(key)
    js_domain = json.dumps(VWORLD_DOMAIN or "localhost")
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{safe_label} · 필지 위치</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  html, body {{ margin:0; height:100%; font-family:'Malgun Gothic','맑은 고딕',sans-serif; }}
  #map {{ height:100%; width:100%; }}
  .info {{ font-size:13px; line-height:1.5; }}
  .info b {{ font-size:14px; }}
</style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  var KEY = {js_key};
  var DOMAIN = {js_domain};
  var LON = {lon}, LAT = {lat};
  var LABEL = {js_label};

  var map = L.map('map').setView([LAT, LON], 18);

  // VWorld 배경지도 (WMTS) — 인증키 도메인이 localhost 면 정상 로드
  var vbase = L.tileLayer(
    'https://api.vworld.kr/req/wmts/1.0.0/' + KEY + '/Base/{{z}}/{{y}}/{{x}}.png',
    {{ maxZoom: 19, attribution: 'VWorld' }}
  ).addTo(map);
  var vsat = L.tileLayer(
    'https://api.vworld.kr/req/wmts/1.0.0/' + KEY + '/Satellite/{{z}}/{{y}}/{{x}}.jpeg',
    {{ maxZoom: 19, attribution: 'VWorld 위성' }}
  );
  // OSM 대체(브이월드 타일이 막힌 환경 대비 — 지도가 비지 않도록)
  var osm = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
    {{ maxZoom: 19, attribution: '© OpenStreetMap' }});

  // 연속지적도(필지 경계) 오버레이 — VWorld WMS
  var cadastral = L.tileLayer.wms('https://api.vworld.kr/req/wms', {{
    key: KEY, domain: DOMAIN,
    layers: 'lp_pa_cbnd_bubun', styles: 'lp_pa_cbnd_bubun',
    format: 'image/png', transparent: true, version: '1.3.0',
    attribution: 'VWorld 지적도'
  }});

  L.control.layers(
    {{ 'VWorld 일반': vbase, 'VWorld 위성': vsat, 'OSM(대체)': osm }},
    {{ '지적경계': cadastral }},
    {{ collapsed: false }}
  ).addTo(map);

  var marker = L.marker([LAT, LON]).addTo(map);
  marker.bindPopup(
    '<div class="info"><b>📍 ' + LABEL + '</b><br>' +
    '경도 ' + LON.toFixed(6) + ' / 위도 ' + LAT.toFixed(6) + '</div>'
  ).openPopup();
</script>
</body>
</html>"""


def _serve_once(page: str) -> int:
    """생성한 HTML 을 localhost 임의 포트로 서빙하고 포트 번호를 반환."""
    body = page.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass  # 콘솔 로그 억제

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    _servers.append(srv)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def open_parcel_map(address: str, label: str = None) -> bool:
    """
    주소의 필지를 브라우저 지도에 연다. 성공 시 True, 좌표 변환 실패 시 False.
    (네트워크 호출이 있으므로 호출부에서 스레드로 실행 권장)
    """
    coord = pnu_util.address_to_coord(address)
    if not coord:
        # 도로명주소로 한 번 더 시도
        coord = pnu_util.address_to_coord(address, addr_type="ROAD")
    if not coord:
        return False
    lon, lat = coord
    page = _map_html(lon, lat, label or address)
    port = _serve_once(page)
    webbrowser.open(f"http://localhost:{port}/")
    return True
