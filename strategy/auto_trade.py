# AutoBitTrade/strategy/auto_grid_trade.py
# 반복형 차수 매매 전략 (무한 반복 매수-매도 구조)
# 1차수 매수 체결 → 매도 체결 → 다시 1차수 매수 무한 반복 전략

import time
import math
from datetime import datetime
from api.api import place_order, get_order_detail, cancel_order_by_uuid
from config.tick_table import TICK_SIZE
from utils.telegram import send_telegram_message, MSG_AUTO_TRADE_START, MSG_BUY_ORDER, MSG_SELL_ORDER, MSG_BUY_FILLED, MSG_SELL_FILLED
from shared.state import strategy_info

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
        print(f"❌ 매수 주문 실패 [{level.level}차]: {res}")

def place_sell(level, market):
    res = place_order(market, 'ask', level.volume, level.sell_price, 'limit')
    uuid = res.get('uuid') or res.get('data', {}).get('uuid')
    if uuid:
        level.sell_uuid = uuid
        print(f"📤 [{level.level}차] 매도 주문 등록: {level.sell_price}원 / {level.volume}개")
        send_telegram_message(MSG_SELL_ORDER.format(market=market, level=level.level, sell_price=level.sell_price, volume=level.volume))
    else:
        print(f"❌ 매도 주문 실패 [{level.level}차]: {res}")

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

    # 누적 수익액 초기화
    realized_profit = 0.0
    strategy_info["realized_profit"] = realized_profit

    # 콜백 중복 방지용 플래그
    callback_flags = {'buy': set(), 'sell': set()}

    # 차수별 그리드 레벨 생성
    levels = []
    for i in range(max_levels):
        raw_buy_price = calculate_price(start_price, buy_gap * i, buy_mode, 'down')
        raw_sell_price = calculate_price(raw_buy_price, sell_gap, sell_mode, 'up')
        buy_price = math.floor(raw_buy_price / tick) * tick
        sell_price = math.floor(raw_sell_price / tick) * tick
        volume = round(krw_amount / buy_price, 8)
        levels.append(GridLevel(i + 1, buy_price, sell_price, volume))

    print(f"📊 자동 매매 시작: {max_levels}차까지 설정됨.")
    send_telegram_message(MSG_AUTO_TRADE_START.format(market=market, max_levels=max_levels, start_price=start_price, krw_amount=krw_amount))

    place_buy(levels[0], market)

    while True:
        if stop_condition and stop_condition():
            print("🛑 사용자 중단 감지. 종료합니다.")
            break

        for level in levels:
            # ✅ 매수 체결 확인
            if level.buy_uuid and not level.buy_filled:
                detail = get_order_detail(level.buy_uuid)
                data = detail.get('data') or detail
                executed = float(data.get('executed_volume', 0))
                remaining = float(data.get('remaining_volume', 0))
                if executed > 0 and remaining == 0:
                    level.buy_filled = True
                    callback_flags['buy'].add(level.level)

                    print(f"✅ [{level.level}차] 매수 체결 완료: {level.buy_price}원")
                    send_telegram_message(MSG_BUY_FILLED.format(market=market, level=level.level, buy_price=level.buy_price, volume=level.volume))

                    # 콜백 함수 호출
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

                    # 📤 현재 차수 매도 주문 등록
                    place_sell(level, market)

                    # 🛒 다음 차수 매수 등록
                    next_idx = level.level
                    if next_idx < len(levels):
                        place_buy(levels[next_idx], market)

            # ✅ 매도 체결 확인
            if level.sell_uuid and not level.sell_filled:
                detail = get_order_detail(level.sell_uuid)
                data = detail.get('data') or detail
                executed = float(data.get('executed_volume', 0))
                remaining = float(data.get('remaining_volume', 0))
                if executed > 0 and remaining == 0:
                    level.sell_filled = True
                    callback_flags['sell'].add(level.level)

                    # ✅ 빗썸 수수료 반영 수익 계산
                    fee_rate = 0.0004

                    # 실거래 기준 수익 계산
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

                    # 선택적으로 callback_flags도 초기화
                    callback_flags['buy'].discard(level.level)
                    callback_flags['sell'].discard(level.level)

                    # 콜백 함수 호출
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

                    # 🛒 현재 차수 매수 등록
                    place_buy(level, market)

                    # 📤 이전 차수 매도 등록
                    prev_idx = level.level - 2
                    if prev_idx >= 0:
                        place_sell(levels[prev_idx], market)


        time.sleep(sleep_sec)
