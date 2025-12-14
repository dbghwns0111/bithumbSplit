# bitsplit/api/api.py
# 빗썸 API와 연동하는 함수 모음

import os
import uuid
import hashlib
import time
import json
from urllib.parse import urlencode
import requests
from requests.exceptions import RequestException
import jwt
from dotenv import load_dotenv
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
if getattr(sys, 'frozen', False):
    # PyInstaller로 패키징된 경우
    base_path = Path(sys.executable).parent
else:
    # 개발 환경
    base_path = Path(__file__).parent.parent

if str(base_path) not in sys.path:
    sys.path.insert(0, str(base_path))

from utils.telegram import send_telegram_message

# .env 파일 로드
load_dotenv()
accessKey = os.getenv("BITHUMB_API_KEY")
secretKey = os.getenv("BITHUMB_API_SECRET")

def _alert(msg: str):
    try:
        send_telegram_message(msg)
    except Exception:
        # 텔레그램 전송 실패는 무시하고 넘어간다.
        pass
apiUrl = 'https://api.bithumb.com'

# 공통: JWT 토큰 생성 함수
def _make_token(query: dict = None):
    payload = {
        'access_key': accessKey,
        'nonce': str(uuid.uuid4()),
        'timestamp': round(time.time() * 1000),
    }

    if query:
        query_string = urlencode(query).encode()
        m = hashlib.sha512()
        m.update(query_string)
        query_hash = m.hexdigest()
        payload['query_hash'] = query_hash
        payload['query_hash_alg'] = 'SHA512'

    jwt_token = jwt.encode(payload, secretKey, algorithm='HS256')
    return {
        'Authorization': f'Bearer {jwt_token}'
    }

# 자산 조회
def get_balance():
    headers = _make_token()
    resp = requests.get(f"{apiUrl}/v1/accounts", headers=headers)
    return resp.json()

# 주문 가능 정보 조회
def get_order_chance(market='KRW-BTC'):
    query = {"market": market}
    headers = _make_token(query)
    resp = requests.get(f"{apiUrl}/v1/orders/chance", params=query, headers=headers)
    return resp.json()

# 주문 실행 함수 (지정가 또는 시장가)
def place_order(market, side, volume, price, ord_type='limit', retries=3, delay=1, backoff=2):
    body = {
        "market": market,
        "side": side,
        "volume": str(volume),
        "price": str(price),
        "ord_type": ord_type
    }
    headers = _make_token(body)
    headers['Content-Type'] = 'application/json'

    cur_delay = delay
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(f"{apiUrl}/v1/orders", headers=headers, data=json.dumps(body), timeout=5)
            return resp.json()
        except RequestException as e:
            if attempt == retries:
                _alert(f"🚨 주문 요청 실패({attempt}/{retries}) {market} {side} {price}: {e}")
                return {"status": "9999", "message": str(e)}
            time.sleep(cur_delay)
            cur_delay *= backoff

# 주문 취소 함수 (UUID 기반)
def cancel_order(order_uuid, retries=3, delay=1, backoff=2):
    param = {'uuid': order_uuid}
    headers = _make_token(param)
    cur_delay = delay
    for attempt in range(1, retries + 1):
        try:
            response = requests.delete(f"{apiUrl}/v1/order", params=param, headers=headers, timeout=5)
            return response.json()
        except RequestException as e:
            if attempt == retries:
                _alert(f"🚨 주문 취소 실패({attempt}/{retries}) {order_uuid}: {e}")
                return {"status": "9999", "message": str(e)}
            time.sleep(cur_delay)
            cur_delay *= backoff

# 개별 주문 조회
def get_order_detail(order_uuid, retries=3, delay=1, backoff=2):
    query = {"uuid": order_uuid}
    headers = _make_token(query)
    cur_delay = delay

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(f"{apiUrl}/v1/order", params=query, headers=headers, timeout=5)
            return resp.json()
        except RequestException as e:
            print(f"[{attempt}/{retries}] 주문 조회 실패: {e}")
            if attempt == retries:
                _alert(f"🚨 주문 조회 실패({attempt}/{retries}) {order_uuid}: {e}")
                return {"status": "9999", "message": str(e)}
            time.sleep(cur_delay)
            cur_delay *= backoff

# 주문 리스트 조회

def get_order_list(market='KRW-BTC', limit=100, page=1, order_by='desc', uuids=None):
    query = {
        "market": market,
        "limit": str(limit),
        "page": str(page),
        "order_by": order_by
    }
    if uuids:
        for i, u in enumerate(uuids):
            query[f"uuids[{i}]"] = u

    headers = _make_token(query)
    resp = requests.get(f"{apiUrl}/v1/orders", params=query, headers=headers)
    return resp.json()

# 전체 주문 취소
def cancel_all_orders(market):
    print(f"📋 {market} 미체결 주문 조회 중...")
    orders = get_order_list(market)

    # 응답이 dict가 아니거나 에러인 경우 처리
    if not isinstance(orders, list):
        if isinstance(orders, dict):
            error_msg = orders.get('message', 'Unknown error')
            print(f"⚠️ 주문 조회 실패: {error_msg}")
        else:
            print(f"⚠️ 주문 조회 실패: 예상치 못한 응답 형식")
        return

    if not orders:
        print("✅ 취소할 주문 없음")
        return

    for order in orders:
        if isinstance(order, dict):
            uuid = order.get("order_id") or order.get("uuid")
            if uuid:
                res = cancel_order(uuid)
                print(f"🗑️ 주문 취소 요청: {uuid} → {res}")
                time.sleep(0.2)

# 현재가 조회
def get_current_price(market='KRW-BTC', retries=3, delay=1, backoff=2):
    query = {"currency": market.split('-')[1]}
    cur_delay = delay

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(f"{apiUrl}/public/ticker/{market}", params=query, timeout=5)
            data = resp.json()
            if data.get('status') == '0000':
                return float(data['data']['closing_price'])
            else:
                msg = data.get('message', 'unknown error')
                print(f"❌ 현재가 조회 실패: {msg}")
                if attempt == retries:
                    _alert(f"🚨 현재가 조회 실패({attempt}/{retries}) {market}: {msg}")
                else:
                    time.sleep(cur_delay)
                    cur_delay *= backoff
        except RequestException as e:
            if attempt == retries:
                _alert(f"🚨 현재가 조회 실패({attempt}/{retries}) {market}: {e}")
                return None
            time.sleep(cur_delay)
            cur_delay *= backoff
    
# 주문 취소 함수
# - 매수 체결 시: (n-1)차 매도 주문 취소 추가
# - 매도 체결 시: (n+1)차 매수 주문 취소 + (n-1)차 매도 주문 재등록
def cancel_order_by_uuid(uuid):
    if uuid:
        res = cancel_order(uuid)
        if res.get('uuid') or res.get('data', {}).get('uuid'):
            print(f"🚫 주문 취소 성공: {uuid}")
        else:
            print(f"⚠️ 주문 취소 실패: {res}")