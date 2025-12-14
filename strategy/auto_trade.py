# bithumbSplit/strategy/auto_grid_trade.py
# 반복형 차수 매매 전략 (무한 반복 매수-매도 구조)
# 1차수 매수 체결 → 매도 체결 → 다시 1차수 매수 무한 반복 전략

import time
import math
from datetime import datetime
import json
import os
import sys
from api.api import place_order, get_order_detail, cancel_order_by_uuid
from config.tick_table import TICK_SIZE
from utils.telegram import send_telegram_message, MSG_AUTO_TRADE_START, MSG_BUY_ORDER, MSG_SELL_ORDER, MSG_BUY_FILLED, MSG_SELL_FILLED
from shared.state import strategy_info

# 상태 저장 파일 경로 헬퍼 (PyInstaller exe 포함)
def _base_dir():
    if getattr(sys, 'frozen', False):  # exe일 때는 실행 파일 위치에 저장
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(__file__))


def _state_path():
    try:
        return os.path.join(_base_dir(), 'logs', 'autotrade_state.json')
    except Exception as e:
        print(f"⚠️ 상태 경로 계산 실패, 현재 작업 경로로 대체: {e}")
        return os.path.join(os.getcwd(), 'logs', 'autotrade_state.json')


def _ensure_state_dir():
    os.makedirs(os.path.dirname(_state_path()), exist_ok=True)


def _load_state():
    try:
        with open(_state_path(), 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"⚠️ 상태 파일 로드 실패: {e}")
        return None


def _save_state(state: dict):
    try:
        _ensure_state_dir()
        with open(_state_path(), 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print(f"💾 상태 저장: {_state_path()}")
    except Exception as e:
        print(f"⚠️ 상태 파일 저장 실패: {e}")


def _serialize_levels(levels):
    serialized = []
    for level in levels:
        serialized.append({
            "level": level.level,
            "buy_price": level.buy_price,
            "sell_price": level.sell_price,
            "volume": level.volume,
            "buy_uuid": level.buy_uuid,
            "sell_uuid": level.sell_uuid,
            "buy_filled": level.buy_filled,
            "sell_filled": level.sell_filled,
        })
    return serialized


def _build_levels(state_levels):
    levels = []
    for lv in state_levels:
        g = GridLevel(lv["level"], lv["buy_price"], lv["sell_price"], lv["volume"])
        g.buy_uuid = lv.get("buy_uuid")
        g.sell_uuid = lv.get("sell_uuid")
        g.buy_filled = lv.get("buy_filled", False)
        g.sell_filled = lv.get("sell_filled", False)
        levels.append(g)
    return levels


def _safe_get_order_detail(order_uuid):
    try:
        return get_order_detail(order_uuid)
    except Exception as e:
        print(f"⚠️ 주문 조회 실패: {order_uuid} / {e}")
        return {"status": "9999", "message": str(e)}


def _params_match(state, market, start_price, krw_amount, max_levels, buy_gap, buy_mode, sell_gap, sell_mode):
    return (
        state.get("market") == market and
        state.get("start_price") == start_price and
        state.get("krw_amount") == krw_amount and
        state.get("max_levels") == max_levels and
        state.get("buy_gap") == buy_gap and
        state.get("buy_mode") == buy_mode and
        state.get("sell_gap") == sell_gap and
        state.get("sell_mode") == sell_mode
    )

# 가격 계산 함수: 퍼센트 또는 고정 금액으로 가격 조정
# mode: 'percent' 또는 'price'
def calculate_price(base_price, gap_value, mode, direction):
    if mode == 'percent':
        rate = (1 + gap_value / 100) if direction == 'up' else (1 - gap_value / 100)
        return round(base_price * rate, 2)
    elif mode == 'price':
        return round(base_price + gap_value, 2) if direction == 'up' else round(base_price - gap_value, 2)
    else:
        raise ValueError("mode는 'percent' 또는 'price' 여야 합니다.")

# 주문 등록 함수: 매수 또는 매도 주문을 API를 통해 실행
def place_buy(level, market):
    res = place_order(market, 'bid', level.volume, level.buy_price, 'limit')
    uuid = res.get('uuid') or res.get('data', {}).get('uuid')
    if uuid:
        level.buy_uuid = uuid
        print(f"🛒 [{level.level}차] 매수 주문 등록: {level.buy_price}원 / {level.volume}개")
        send_telegram_message(MSG_BUY_ORDER.format(market=market, level=level.level, buy_price=level.buy_price, volume=level.volume))
    else:
        # [수정] 오류 응답 전체를 보기 쉽게 출력
        error_msg = json.dumps(res, indent=4, ensure_ascii=False)
        print(f"❌ 매수 주문 실패 [{level.level}차]:\n{error_msg}")
        # print(f"❌ 매수 주문 실패 [{level.level}차]: {res}") # 기존 코드

def place_sell(level, market):
    res = place_order(market, 'ask', level.volume, level.sell_price, 'limit')
    uuid = res.get('uuid') or res.get('data', {}).get('uuid')
    if uuid:
        level.sell_uuid = uuid
        print(f"📤 [{level.level}차] 매도 주문 등록: {level.sell_price}원 / {level.volume}개")
        send_telegram_message(MSG_SELL_ORDER.format(market=market, level=level.level, sell_price=level.sell_price, volume=level.volume))
    else:
        # [수정] 오류 응답 전체를 보기 쉽게 출력
        error_msg = json.dumps(res, indent=4, ensure_ascii=False)
        print(f"❌ 매도 주문 실패 [{level.level}차]:\n{error_msg}")
        # print(f"❌ 매도 주문 실패 [{level.level}차]: {res}") # 기존 코드

# 그리드 레벨 클래스: 각 차수의 매수/매도 가격과 수량을 관리
# 레벨(level), 매수 가격(buy_price), 매도 가격(sell_price),
class GridLevel:
    def __init__(self, level, buy_price, sell_price, volume):
        self.level = level
        self.buy_price = buy_price
        self.sell_price = sell_price
        self.volume = volume
        self.buy_uuid = None
        self.sell_uuid = None
        self.buy_filled = False
        self.sell_filled = False

# 자동 매매 실행 함수: 시작 가격, 원화 금액, 최대 차수, 매수/매도 간격 등을 설정
def run_auto_trade(start_price, krw_amount, max_levels,
                   buy_gap, buy_mode, sell_gap, sell_mode,
                   market_code='USDT', sleep_sec=5,
                   stop_condition=None, status_callback=None,
                   summary_callback=None):

    market_code = market_code.upper()
    market = f"KRW-{market_code}"
    tick = TICK_SIZE.get(market)
    if tick is None:
        print(f"❌ 호가단위가 정의되지 않은 종목입니다: {market}")
        return
    # 기존 상태 복원 시도
    loaded_state = _load_state()
    resume_state = None
    if loaded_state and _params_match(loaded_state, market, start_price, krw_amount, max_levels, buy_gap, buy_mode, sell_gap, sell_mode):
        resume_state = loaded_state

    if resume_state:
        realized_profit = resume_state.get("realized_profit", 0.0)
        levels = _build_levels(resume_state.get("levels", []))
        print(f"⏯️ 기존 상태 발견. {market} / {len(levels)}차 재개")
    else:
        realized_profit = 0.0
        # 차수별 그리드 레벨 생성
        levels = []
        for i in range(max_levels):
            raw_buy_price = calculate_price(start_price, buy_gap * i, buy_mode, 'down')
            raw_sell_price = calculate_price(raw_buy_price, sell_gap, sell_mode, 'up')
            buy_price = math.floor(raw_buy_price / tick) * tick
            sell_price = math.floor(raw_sell_price / tick) * tick
            volume = round(krw_amount / buy_price, 8)
            levels.append(GridLevel(i + 1, buy_price, sell_price, volume))

    strategy_info.update({
        "market": market,
        "start_price": start_price,
        "current_price": start_price,
        "realized_profit": realized_profit,
    })

    # 콜백 중복 방지용 플래그
    callback_flags = {'buy': set(), 'sell': set()}

    def persist_state():
        snapshot = {
            "market": market,
            "start_price": start_price,
            "krw_amount": krw_amount,
            "max_levels": max_levels,
            "buy_gap": buy_gap,
            "buy_mode": buy_mode,
            "sell_gap": sell_gap,
            "sell_mode": sell_mode,
            "sleep_sec": sleep_sec,
            "realized_profit": realized_profit,
            "levels": _serialize_levels(levels),
        }
        _save_state(snapshot)

    if not resume_state:
        print(f"📊 자동 매매 시작: {max_levels}차까지 설정됨.")
        send_telegram_message(MSG_AUTO_TRADE_START.format(market=market, max_levels=max_levels, start_price=start_price, krw_amount=krw_amount))
        place_buy(levels[0], market)
        persist_state()
    else:
        print("📂 저장된 상태로 재시작합니다. 보류 주문/체결 여부를 동기화합니다.")
        
        # 주문/체결 동기화: 저장된 uuid 상태 확인
        for level in levels:
            # 기존 주문 상태 확인
            if level.buy_uuid and not level.buy_filled:
                detail = _safe_get_order_detail(level.buy_uuid)
                data = detail.get('data') or detail
                executed = float(data.get('executed_volume', 0) or 0)
                remaining = float(data.get('remaining_volume', 0) or 0)
                # 주문이 존재하지 않거나 완전히 체결된 경우 플래그 반영
                if executed > 0 and remaining == 0:
                    level.buy_filled = True
                elif detail.get('status') not in (None, '0000'):
                    level.buy_uuid = None  # 조회 실패 → 재주문 대상으로 전환

            if level.sell_uuid and not level.sell_filled:
                detail = _safe_get_order_detail(level.sell_uuid)
                data = detail.get('data') or detail
                executed = float(data.get('executed_volume', 0) or 0)
                remaining = float(data.get('remaining_volume', 0) or 0)
                if executed > 0 and remaining == 0:
                    level.sell_filled = True
                elif detail.get('status') not in (None, '0000'):
                    level.sell_uuid = None

        # 가장 최근 체결된 매수 차수 찾기
        last_filled_buy_level = None
        for level in levels:
            if level.buy_filled:
                last_filled_buy_level = level
        
        # 재가동 메시지 전송 (차수 정보 포함)
        if last_filled_buy_level:
            resume_info = f"🔄 재가동 차수: {last_filled_buy_level.level}차 매도 + {last_filled_buy_level.level + 1}차 매수"
        else:
            resume_info = "🔄 재가동 차수: 1차 매수"
        
        send_telegram_message(f"⏯️ [전략 재가동]\n📍코인: {market}\n🔢 전체 차수: {max_levels}차\n{resume_info}\n💵 시작가: {start_price:,.1f}원\n💰 누적 수익: {realized_profit:,.0f}원")

        # 재개 시 필요한 주문만 재등록 (현재 진행 중인 차수만)
        if last_filled_buy_level:
            # 가장 최근 매수 체결 차수의 매도 주문이 없으면 재등록
            if not last_filled_buy_level.sell_filled and not last_filled_buy_level.sell_uuid:
                place_sell(last_filled_buy_level, market)
                if status_callback:
                    status_callback(last_filled_buy_level.level, f"[{last_filled_buy_level.level}차] 매수 체결 ✅ / 매도 대기")
            
            # 다음 차수 매수 주문이 없으면 재등록
            next_idx = last_filled_buy_level.level
            if next_idx < len(levels):
                next_level = levels[next_idx]
                if not next_level.buy_filled and not next_level.buy_uuid:
                    place_buy(next_level, market)
                    if status_callback:
                        status_callback(next_level.level, f"[{next_level.level}차] 매수 주문 등록")
        else:
            # 아무것도 체결 안 된 경우 1차 매수만 재등록
            if not levels[0].buy_filled and not levels[0].buy_uuid:
                place_buy(levels[0], market)
                if status_callback:
                    status_callback(levels[0].level, f"[{levels[0].level}차] 매수 주문 등록")

        persist_state()

    # 재개 시 주문이 하나도 없으면 1차 매수부터 다시 등록
    if resume_state:
        has_pending = any((lv.buy_uuid or lv.sell_uuid) for lv in levels)
        if not has_pending:
            place_buy(levels[0], market)
            persist_state()

    while True:
        if stop_condition and stop_condition():
            print("🛑 사용자 중단 감지. 종료합니다.")
            persist_state()
            break

        try:
            for level in levels:
                # ✅ 매수 체결 확인
                if level.buy_uuid and not level.buy_filled:
                    detail = _safe_get_order_detail(level.buy_uuid)
                    data = detail.get('data') or detail
                    executed = float(data.get('executed_volume', 0))
                    remaining = float(data.get('remaining_volume', 0))
                    if executed > 0 and remaining == 0:
                        level.buy_filled = True
                        callback_flags['buy'].add(level.level)

                        print(f"✅ [{level.level}차] 매수 체결 완료: {level.buy_price}원")
                        send_telegram_message(MSG_BUY_FILLED.format(market=market, level=level.level, buy_price=level.buy_price, volume=level.volume))

                        if status_callback:
                            status_callback(level.level, f"[{level.level}차] 매수 체결 ✅ / 매도 대기")

                        # ✅ 모든 기존 주문 취소
                        for lv in levels:
                            if lv.buy_uuid and not lv.buy_filled:
                                cancel_order_by_uuid(lv.buy_uuid)
                                lv.buy_uuid = None
                            if lv.sell_uuid and not lv.sell_filled:
                                cancel_order_by_uuid(lv.sell_uuid)
                                lv.sell_uuid = None

                        persist_state()

                        # 📤 현재 차수 매도 주문 등록
                        place_sell(level, market)
                        persist_state()

                        # 🛒 다음 차수 매수 등록
                        next_idx = level.level
                        if next_idx < len(levels):
                            place_buy(levels[next_idx], market)
                            persist_state()

                # ✅ 매도 체결 확인
                if level.sell_uuid and not level.sell_filled:
                    detail = _safe_get_order_detail(level.sell_uuid)
                    data = detail.get('data') or detail
                    executed = float(data.get('executed_volume', 0))
                    remaining = float(data.get('remaining_volume', 0))
                    if executed > 0 and remaining == 0:
                        level.sell_filled = True
                        callback_flags['sell'].add(level.level)

                        # ✅ 빗썸 수수료 반영 수익 계산
                        fee_rate = 0.0004

                        buy_cost = level.buy_price * (1 + fee_rate)
                        sell_income = level.sell_price * (1 - fee_rate)
                        profit = (sell_income - buy_cost) * level.volume

                        realized_profit += profit
                        strategy_info["realized_profit"] = realized_profit

                        print(f"💰 [{level.level}차] 매도 체결 완료: {level.sell_price}원 / 수익 {profit:.0f}원")
                        send_telegram_message(MSG_SELL_FILLED.format(market=market, level=level.level, sell_price=level.sell_price, volume=level.volume, profit=profit, realized_profit=realized_profit))

                        # level 상태 초기화
                        level.buy_uuid = None
                        level.buy_filled = False
                        level.sell_uuid = None
                        level.sell_filled = False

                        callback_flags['buy'].discard(level.level)
                        callback_flags['sell'].discard(level.level)

                        if status_callback:
                            status_callback(level.level, f"[{level.level}차] 매도 체결 ✅ / 수익 {profit:.0f}원")
                        if summary_callback:
                            summary_callback()

                        # ✅ 모든 기존 주문 취소
                        for lv in levels:
                            if lv.buy_uuid and not lv.buy_filled:
                                cancel_order_by_uuid(lv.buy_uuid)
                                lv.buy_uuid = None
                            if lv.sell_uuid and not lv.sell_filled:
                                cancel_order_by_uuid(lv.sell_uuid)
                                lv.sell_uuid = None

                        persist_state()

                        # 🛒 현재 차수 매수 등록
                        place_buy(level, market)
                        persist_state()

                        # 📤 이전 차수 매도 등록
                        prev_idx = level.level - 2
                        if prev_idx >= 0:
                            place_sell(levels[prev_idx], market)
                            persist_state()

        except Exception as loop_error:
            print(f"⚠️ 루프 처리 중 오류 발생: {loop_error}")
            persist_state()

        time.sleep(sleep_sec)
