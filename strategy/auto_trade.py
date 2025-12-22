# bithumbSplit/strategy/auto_grid_trade.py
# 반복형 차수 매매 전략 (무한 반복 매수-매도 구조)
# 1차수 매수 체결 → 매도 체결 → 다시 1차수 매수 무한 반복 전략

import time
import math
from datetime import datetime
import json
import os
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
if getattr(sys, 'frozen', False):
    base_path = Path(sys.executable).parent
else:
    base_path = Path(__file__).parent.parent

if str(base_path) not in sys.path:
    sys.path.insert(0, str(base_path))

from api.api import place_order, get_order_detail, cancel_order_by_uuid
from config.tick_table import TICK_SIZE
from utils.telegram import send_telegram_message, MSG_AUTO_TRADE_START, MSG_BUY_ORDER, MSG_SELL_ORDER, MSG_BUY_FILLED, MSG_SELL_FILLED
from shared.state import strategy_info

# 상태 저장 파일 경로 헬퍼 (PyInstaller exe 포함)
def _base_dir():
    if getattr(sys, 'frozen', False):  # exe일 때는 실행 파일 위치에 저장
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(__file__))


def _state_path(market='KRW-BTC'):
    try:
        # 파일명에 코인 정보 포함 (예: autotrade_state_KRW_BTC.json)
        filename = f'autotrade_state_{market.replace("-", "_")}.json'
        return os.path.join(_base_dir(), 'logs', filename)
    except Exception as e:
        print(f"⚠️ 상태 경로 계산 실패, 현재 작업 경로로 대체: {e}")
        filename = f'autotrade_state_{market.replace("-", "_")}.json'
        return os.path.join(os.getcwd(), 'logs', filename)


def _ensure_state_dir(market='KRW-BTC'):
    os.makedirs(os.path.dirname(_state_path(market)), exist_ok=True)


def _load_state(market='KRW-BTC'):
    try:
        with open(_state_path(market), 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"⚠️ 상태 파일 로드 실패: {e}")
        return None


def _save_state(state: dict, market='KRW-BTC'):
    try:
        _ensure_state_dir(market)
        with open(_state_path(market), 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print(f"💾 상태 저장: {_state_path(market)}")
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


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_order_filled(data: dict):
    """다양한 필드명을 허용하여 체결 여부를 판별한다."""
    state = str(data.get('state') or data.get('ord_state') or data.get('order_state') or '').lower()
    status_text = str(data.get('status_text') or '').lower()

    executed = _safe_float(
        data.get('executed_volume')
        or data.get('executed_qty')
        or data.get('acc_trade_volume')
        or data.get('traded_volume')
    )
    remaining = _safe_float(
        data.get('remaining_volume')
        or data.get('remaining_qty')
        or data.get('remain_qty')
        or data.get('remain_volume')
    )

    done_states = {'done', 'completed', 'filled', 'fully_filled', 'terminated'}
    if state in done_states or status_text in done_states:
        return True, executed, remaining

    if executed > 0 and remaining <= 1e-12:
        return True, executed, remaining

    if remaining == 0 and (state or status_text):
        return True, executed, remaining

    return False, executed, remaining


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
    """매수 주문 등록 후 성공 여부 반환"""
    res = place_order(market, 'bid', level.volume, level.buy_price, 'limit')
    uuid = res.get('uuid') or res.get('data', {}).get('uuid')
    if uuid:
        level.buy_uuid = uuid
        print(f"🛒 [{level.level}차] 매수 주문 등록: {level.buy_price}원 / {level.volume}개")
        order_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        send_telegram_message(
            MSG_BUY_ORDER.format(
                market=market,
                level=level.level,
                buy_price=level.buy_price,
                volume=level.volume,
                order_time=order_time,
            )
        )
        return True

    error_msg = json.dumps(res, indent=4, ensure_ascii=False)
    print(f"❌ 매수 주문 실패 [{level.level}차]:\n{error_msg}")
    send_telegram_message(f"❌ [{level.level}차] 매수 주문 실패\n📍코인: {market}\n사유: {res}")
    return False

def place_sell(level, market):
    """매도 주문 등록 후 성공 여부 반환"""
    res = place_order(market, 'ask', level.volume, level.sell_price, 'limit')
    uuid = res.get('uuid') or res.get('data', {}).get('uuid')
    if uuid:
        level.sell_uuid = uuid
        print(f"📤 [{level.level}차] 매도 주문 등록: {level.sell_price}원 / {level.volume}개")
        order_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        send_telegram_message(
            MSG_SELL_ORDER.format(
                market=market,
                level=level.level,
                sell_price=level.sell_price,
                volume=level.volume,
                order_time=order_time,
            )
        )
        return True

    error_msg = json.dumps(res, indent=4, ensure_ascii=False)
    print(f"❌ 매도 주문 실패 [{level.level}차]:\n{error_msg}")
    send_telegram_message(f"❌ [{level.level}차] 매도 주문 실패\n📍코인: {market}\n사유: {res}")
    return False

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
                   summary_callback=None, resume_level=0):

    market_code = market_code.upper()
    market = f"KRW-{market_code}"
    tick = TICK_SIZE.get(market)
    if tick is None:
        print(f"❌ 호가단위가 정의되지 않은 종목입니다: {market}")
        return
    
    # resume_level 처리: 0이면 새 시작 또는 상태 파일 복원, 1 이상이면 수동 재시작
    manual_resume = resume_level > 0
    
    # 기존 상태 복원 시도 (resume_level=0일 때만)
    loaded_state = _load_state(market)
    resume_state = None
    if not manual_resume and loaded_state and _params_match(loaded_state, market, start_price, krw_amount, max_levels, buy_gap, buy_mode, sell_gap, sell_mode):
        resume_state = loaded_state

    if resume_state:
        realized_profit = resume_state.get("realized_profit", 0.0)
        levels = _build_levels(resume_state.get("levels", []))
        
        # 체결 이력 복구 및 검증
        saved_trade_history = resume_state.get("trade_history", [])
        if saved_trade_history:
            recalculated_profit = sum(trade.get("profit", 0) for trade in saved_trade_history)
            print(f"📊 체결 이력: {len(saved_trade_history)}건 / 재계산 수익: {recalculated_profit:,.0f}원")
            
            # realized_profit 불일치 시 체결 이력 기반으로 복구
            if abs(realized_profit - recalculated_profit) > 1:
                print(f"⚠️ 누적 수익 불일치 - 체결 이력으로 복구: {realized_profit:,.0f}원 → {recalculated_profit:,.0f}원")
                realized_profit = recalculated_profit
        
        print(f"⏯️ 기존 상태 발견. {market} / {len(levels)}차 재개 / 누적 수익: {realized_profit:,.0f}원")
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

    # 체결 이력 저장용 (realized_profit 복구용)
    trade_history = resume_state.get("trade_history", []) if resume_state else []

    def build_active_orders():
        """현재 미체결 주문을 uuid 중심으로 매핑해 중복 주문을 방지한다."""
        try:
            from api.api import get_order_list
            order_list = get_order_list(market=market, limit=100)
        except Exception as e:  # 네트워크 오류 등은 빈 결과로 처리
            print(f"⚠️ 활성 주문 조회 실패: {e}")
            return {}, None

        active_orders = {}
        if isinstance(order_list, list):
            for order in order_list:
                uuid = order.get('uuid') or order.get('order_id')
                if not uuid:
                    continue
                active_orders[uuid] = {
                    'side': order.get('side'),
                    'price': float(order.get('price', 0) or 0),
                    'volume': float(order.get('volume', 0) or 0),
                }
        return active_orders, order_list if isinstance(order_list, list) else None

    def find_matching_order(active_orders, side, target_price, target_volume):
        """가격·수량이 유사한 주문을 찾아 uuid를 재연결한다."""
        price_tol = max(tick, target_price * 0.001)  # 0.1% 또는 한 틱
        volume_tol = max(target_volume * 0.02, 1e-10)  # 2% 허용치
        for uuid, info in active_orders.items():
            if info['side'] != side:
                continue
            if abs(info['price'] - target_price) > price_tol:
                continue
            if abs(info['volume'] - target_volume) > volume_tol:
                continue
            return uuid
        return None

    def reattach_missing_orders():
        """상태에 uuid가 없지만 실제 주문이 남아있다면 다시 연결한다."""
        active_orders, order_list = build_active_orders()
        if not active_orders:
            return set(), order_list

        attached_levels = set()
        for level in levels:
            if not level.buy_filled and not level.buy_uuid:
                matched = find_matching_order(active_orders, 'bid', level.buy_price, level.volume)
                if matched:
                    level.buy_uuid = matched
                    attached_levels.add(f"{level.level}차 매수")
            if not level.sell_filled and not level.sell_uuid:
                matched = find_matching_order(active_orders, 'ask', level.sell_price, level.volume)
                if matched:
                    level.sell_uuid = matched
                    attached_levels.add(f"{level.level}차 매도")

        if attached_levels:
            print(f"🔗 누락 uuid 복구: {', '.join(sorted(attached_levels))}")
            persist_state()
        return attached_levels, order_list
    
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
            "trade_history": trade_history,  # 체결 이력 추가
            "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        _save_state(snapshot, market)

    def _write_heartbeat():
        """주기적으로 헬스 상태를 파일에 기록 (외부 Watchdog 감시용)"""
        try:
            heartbeat_file = os.path.join(_base_dir(), 'logs', f'heartbeat_{market.replace("-", "_")}.json')
            _ensure_state_dir(market)
            
            heartbeat = {
                "market": market,
                "timestamp": datetime.now().isoformat(),
                "status": "running",
                "realized_profit": realized_profit,
                "last_buy_level": next((lv.level for lv in reversed(levels) if lv.buy_filled), 0),
                "pending_orders": sum(1 for lv in levels if lv.buy_uuid or lv.sell_uuid),
            }
            with open(heartbeat_file, 'w', encoding='utf-8') as f:
                json.dump(heartbeat, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 헬스 하트비트 저장 실패: {e}")

    def place_pair_orders(sell_target=None, buy_target=None):
        """고변동성에서도 주문쌍이 반드시 만들어지도록 보호 로직."""
        if not sell_target and not buy_target:
            return

        def _register_pair():
            if sell_target:
                place_sell(sell_target, market)
                time.sleep(0.1)  # 매수보다 먼저 매도를 올려 자산 보유분을 시장에 노출
            if buy_target:
                place_buy(buy_target, market)

        # 1차 시도
        _register_pair()

        # 검증: 실제 주문이 올라갔는지 확인, 부족하면 한 번 더 시도
        active_orders, order_list = build_active_orders()
        if order_list is None:
            return

        desired = []
        if sell_target:
            desired.append(('ask', sell_target.sell_price, sell_target.volume, 'sell'))
        if buy_target:
            desired.append(('bid', buy_target.buy_price, buy_target.volume, 'buy'))

        missing = []
        for side, price, volume, label in desired:
            matched = find_matching_order(active_orders, side, price, volume)
            if not matched:
                missing.append(label)
            else:
                if side == 'ask':
                    sell_target.sell_uuid = matched
                else:
                    buy_target.buy_uuid = matched

        if missing:
            print(f"⚠️ 주문쌍 일부 미등록 감지 → 재시도: {', '.join(missing)}")
            try:
                from api.api import cancel_all_orders
                cancel_all_orders(market)
            except Exception as e:
                print(f"⚠️ 주문쌍 재시도 전 전체 취소 실패: {e}")
            _register_pair()
            persist_state()

    # 수동 재시작 처리 (resume_level > 0)
    if manual_resume:
        print(f"🔄 수동 재시작: {resume_level}차부터 시작합니다.")
        
        # 모든 기존 주문 취소
        try:
            from api.api import cancel_all_orders
            print("🚫 모든 기존 주문 취소 중...")
            cancel_all_orders(market)
        except Exception as e:
            print(f"⚠️ 기존 주문 취소 중 오류: {e}")
        
        # resume_level-1 차수까지는 매수/매도 모두 완료로 설정
        for i in range(resume_level - 1):
            levels[i].buy_filled = True
            levels[i].sell_filled = True
            levels[i].buy_uuid = None
            levels[i].sell_uuid = None
        
        # resume_level 차수부터는 미체결 상태로 유지
        # resume_level 차수 매수 주문 등록
        buy_ok = False
        if resume_level <= len(levels):
            current_level = levels[resume_level - 1]  # resume_level차 (인덱스는 -1)
            buy_ok = place_buy(current_level, market)

        # resume_level-1 차수 매도 주문 등록 (있다면)
        sell_ok = False
        if resume_level > 1:
            prev_level = levels[resume_level - 2]  # resume_level-1차
            prev_level.buy_filled = True  # 이전 차수는 매수 체결된 상태
            prev_level.sell_filled = False
            sell_ok = place_sell(prev_level, market)

        # 주문 실패 시 사용자 알림 후 종료
        if not buy_ok:
            send_telegram_message(
                f"❌ [수동 재시작 실패]\n"
                f"📍코인: {market}\n"
                f"🔢 재시작 차수: {resume_level}차\n"
                f"사유: 매수 주문이 등록되지 않았습니다."
            )
            return

        # 상태 저장 (주문 uuid 반영)
        persist_state()

        # 텔레그램 메시지 구성 (성공한 주문만 포함)
        if resume_level > 1 and sell_ok:
            order_info = f"⚠️ {resume_level}차 매수 + {resume_level - 1}차 매도 주문 등록됨"
        elif resume_level > 1 and not sell_ok:
            order_info = f"⚠️ {resume_level}차 매수 등록, {resume_level - 1}차 매도 등록 실패"
        else:
            order_info = f"⚠️ {resume_level}차 매수 주문 등록됨"

        send_telegram_message(
            f"🔄 [수동 재시작]\n"
            f"📍코인: {market}\n"
            f"🔢 재시작 차수: {resume_level}차\n"
            f"📊 전체 차수: {max_levels}차\n"
            f"💵 시작가: {start_price:,.1f}원\n"
            f"💰 누적 수익: {realized_profit:,.0f}원\n"
            f"{order_info}"
        )
    
    elif not resume_state:
        print(f"📊 자동 매매 시작: {max_levels}차까지 설정됨.")
        send_telegram_message(MSG_AUTO_TRADE_START.format(market=market, max_levels=max_levels, start_price=start_price, krw_amount=krw_amount))
        place_buy(levels[0], market)
        persist_state()
    else:
        print("📂 저장된 상태로 재시작합니다. 보류 주문/체결 여부를 동기화합니다.")
        
        # 1단계: 저장된 uuid 상태 확인
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
        
        # 1-1단계: 잔고 기반 복구 (UUID로 확인 불가능한 경우)
        try:
            from api.api import get_balance
            print("💰 잔고 기반 복구 시스템 작동 중...")
            
            balance_data = get_balance()
            coin_balance = 0.0
            
            # 해당 코인의 잔고 확인
            if isinstance(balance_data, list):
                for item in balance_data:
                    if item.get('currency') == market_code:
                        coin_balance = float(item.get('balance', 0))
                        locked_balance = float(item.get('locked', 0))
                        total_coin = coin_balance + locked_balance
                        print(f"   현재 {market_code} 보유: {coin_balance:.8f} (락업: {locked_balance:.8f}, 총: {total_coin:.8f})")
                        break
            
            # 잔고로 추정되는 매수 체결 차수 계산
            if coin_balance > 0.000001:  # 잔고가 있으면
                expected_holdings = []
                for level in levels:
                    if level.buy_filled and not level.sell_filled:
                        expected_holdings.append((level.level, level.volume))
                
                total_expected = sum(v for _, v in expected_holdings)
                
                # 실제 잔고와 예상 잔고 차이 확인
                diff_ratio = abs(coin_balance - total_expected) / max(total_expected, 0.00000001)
                
                if diff_ratio > 0.1:  # 10% 이상 차이 나면
                    print(f"⚠️ 잔고 불일치 감지: 예상 {total_expected:.8f} vs 실제 {coin_balance:.8f}")
                    
                    # 잔고로 역추적하여 체결 상태 재구성
                    reconstructed_levels = []
                    remaining_balance = coin_balance
                    
                    for level in reversed(levels):  # 높은 차수부터 역순으로
                        if remaining_balance >= level.volume * 0.99:  # 약간의 오차 허용
                            level.buy_filled = True
                            level.sell_filled = False
                            level.buy_uuid = None
                            level.sell_uuid = None
                            remaining_balance -= level.volume
                            reconstructed_levels.append(level.level)
                            print(f"   ✅ {level.level}차 매수 체결로 재구성 (수량: {level.volume:.8f})")
                    
                    if reconstructed_levels:
                        send_telegram_message(
                            f"🔄 [잔고 기반 복구]\n"
                            f"📍코인: {market}\n"
                            f"💰 현재 잔고: {coin_balance:.8f} {market_code}\n"
                            f"📊 복구된 차수: {', '.join(map(str, reversed(reconstructed_levels)))}차\n"
                            f"⚠️ UUID 정보 없음 - 잔고로 재구성함"
                        )
                else:
                    print(f"✅ 잔고 일치: 예상 {total_expected:.8f} vs 실제 {coin_balance:.8f}")
            else:
                print("   보유 코인 없음 - 정상")
        
        except Exception as e:
            print(f"⚠️ 잔고 기반 복구 중 오류: {e}")
        
        # 1-2단계: 주문 uuid 누락분 재연결 (중복 주문 방지)
        attached_levels, cached_order_list = reattach_missing_orders()

        # 2단계: 고아 주문 감지 (코드가 인식하지 못하는 주문)
        try:
            from api.api import get_order_list
            print("🔍 고아 주문 감지 중...")
            order_list = cached_order_list or get_order_list(market=market, limit=100)
            
            if isinstance(order_list, list):
                tracked_uuids = set()
                for level in levels:
                    if level.buy_uuid:
                        tracked_uuids.add(level.buy_uuid)
                    if level.sell_uuid:
                        tracked_uuids.add(level.sell_uuid)
                
                orphan_orders = []
                for order in order_list:
                    order_uuid = order.get('uuid') or order.get('order_id')
                    if order_uuid and order_uuid not in tracked_uuids:
                        orphan_orders.append(order)
                
                if orphan_orders:
                    print(f"⚠️ {len(orphan_orders)}개의 고아 주문 발견 - 취소합니다:")
                    for order in orphan_orders:
                        order_uuid = order.get('uuid') or order.get('order_id')
                        side = order.get('side')
                        price = float(order.get('price', 0))
                        volume = float(order.get('volume', 0))
                        print(f"   - {side} {price:,.0f}원 x {volume:.8f} (UUID: {order_uuid})")
                        cancel_order_by_uuid(order_uuid)
                    send_telegram_message(f"🗑️ [고아 주문 정리]\n📍코인: {market}\n🔢 취소된 주문: {len(orphan_orders)}개")
                else:
                    print("✅ 고아 주문 없음")
        except Exception as e:
            print(f"⚠️ 고아 주문 감지 중 오류: {e}")

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

    # 재개 시 주문이 하나도 없으면 마지막 체결 차수 기준으로 재등록
    if resume_state:
        has_pending = any((lv.buy_uuid or lv.sell_uuid) for lv in levels)
        if not has_pending:
            last_filled_level = max([lv.level for lv in levels if lv.buy_filled], default=0)

            sell_target = None
            if last_filled_level >= 2:
                candidate = levels[last_filled_level - 2]  # 직전 차수 매도
                if not candidate.sell_filled:
                    sell_target = candidate

            buy_target = levels[last_filled_level] if last_filled_level < len(levels) else None

            place_pair_orders(sell_target=sell_target, buy_target=buy_target)
            persist_state()

    # 헬스체크 카운터 (주기적으로 자동매매 상태 검증)
    health_check_counter = 0
    health_check_interval = 12  # 12번 루프마다 검증 (sleep_sec=5초 기준 약 1분)
    
    # 하트비트 카운터 (주기적으로 살아있음 신호 전송)
    heartbeat_counter = 0
    heartbeat_interval = 6  # 6번 루프마다 하트비트 (sleep_sec=5초 기준 약 30초)

    def perform_health_check():
        """자동매매 상태 검증 및 자동 복구"""
        try:
            print("🏥 [헬스체크] 자동매매 상태 검증 중...")

            # 1. 현재 주문 목록 조회 + uuid 매핑
            active_orders, order_list = build_active_orders()
            if order_list is None:
                print("⚠️ [헬스체크] 주문 목록 조회 실패")
                return

            # 2. 진행 상태 파악: 열린 주문/최근 체결 기반으로 타깃 결정
            def infer_targets():
                sell_target_local = None
                buy_target_local = None

                # 2-1) 열린 매도 주문(ask) 중 가장 높은 차수를 우선 타깃
                for lvl in levels:
                    if lvl.sell_uuid and lvl.sell_uuid in active_orders:
                        if not sell_target_local or lvl.level > sell_target_local.level:
                            sell_target_local = lvl

                # 2-2) 열린 매수 주문(bid) 중 가장 높은 차수를 보조 타깃
                for lvl in levels:
                    if lvl.buy_uuid and lvl.buy_uuid in active_orders:
                        if not buy_target_local or lvl.level > buy_target_local.level:
                            buy_target_local = lvl

                # 2-3) 매도 타깃이 있고 매수 타깃이 없으면 N차 매도, N+1차 매수 구조 보장
                if sell_target_local and not buy_target_local:
                    if sell_target_local.level < len(levels):
                        buy_target_local = levels[sell_target_local.level]

                # 2-3-1) 매수만 열려 있고 직전 차수 매도가 없으면 보완: (buy_level-1)차 매도 필요
                if buy_target_local and not sell_target_local:
                    prev_idx = buy_target_local.level - 2
                    if prev_idx >= 0:
                        candidate = levels[prev_idx]
                        if not candidate.sell_filled:
                            sell_target_local = candidate

                # 2-4) 열린 주문이 없으면 최근 체결 이력으로 추론 (마지막 체결 차수의 다음 차수 매수)
                if not sell_target_local and not buy_target_local:
                    last_level = None
                    if trade_history:
                        last_level = max(tr['level'] for tr in trade_history if 'level' in tr)
                    if last_level:
                        if last_level < len(levels):
                            buy_target_local = levels[last_level]
                    else:
                        buy_target_local = levels[0]

                # 2-5) 모든 추론 실패 시 기본 1차 매수
                if not sell_target_local and not buy_target_local:
                    buy_target_local = levels[0]

                return sell_target_local, buy_target_local

            sell_target, buy_target = infer_targets()

            # 활성 주문이 타깃과 일치하는지 확인
            desired_orders = []
            if sell_target:
                desired_orders.append(('ask', sell_target.sell_price, sell_target.volume, sell_target))
            if buy_target:
                desired_orders.append(('bid', buy_target.buy_price, buy_target.volume, buy_target))

            # 활성 주문과 매칭 시도 (유사 가격/수량으로 연결 후 여분/누락 판단)
            remaining_active = set(active_orders.keys())
            issues_found = []

            for side, price, volume, lvl in desired_orders:
                expected_uuid = lvl.sell_uuid if side == 'ask' else lvl.buy_uuid
                if expected_uuid and expected_uuid in active_orders:
                    remaining_active.discard(expected_uuid)
                    continue

                matched_uuid = find_matching_order(active_orders, side, price, volume)
                if matched_uuid:
                    if side == 'ask':
                        lvl.sell_uuid = matched_uuid
                    else:
                        lvl.buy_uuid = matched_uuid
                    remaining_active.discard(matched_uuid)
                    persist_state()
                else:
                    issues_found.append(f"{lvl.level}차 {'매도' if side == 'ask' else '매수'} 주문 없음")

            # 여분 주문 존재 여부
            extra_orders = list(remaining_active)
            if extra_orders:
                issues_found.append(f"불필요 주문 {len(extra_orders)}건")

            # 불일치가 있으면 전체 취소 후 정확한 1쌍(혹은 1개)만 등록
            if issues_found:
                try:
                    from api.api import cancel_all_orders
                    print(f"🚫 [헬스체크] 이상 감지 → 전체 주문 취소 후 재등록: {', '.join(issues_found)}")
                    cancel_all_orders(market)
                except Exception as e:
                    print(f"⚠️ [헬스체크] 전체 취소 실패: {e}")

                # 상태 초기화 (uuid 제거)
                for lvl in levels:
                    lvl.buy_uuid = None
                    lvl.sell_uuid = None

                # 타깃 주문 재등록 (쌍으로 강제 등록)
                place_pair_orders(sell_target=sell_target, buy_target=buy_target)
                persist_state()

                send_telegram_message(
                    f"🔧 [자동복구]\n"
                    f"📍코인: {market}\n"
                    f"🔄 조치: 전체 주문 취소 후 재등록\n"
                    f"📊 등록 상태: "
                    f"{sell_target.level if sell_target else '-'}차 매도 / "
                    f"{buy_target.level if buy_target else '-'}차 매수"
                )
                return

            # 불일치 없으면 정상
            print("✅ [헬스체크] 정상 작동 중")

        except Exception as e:
            print(f"⚠️ [헬스체크] 검증 중 오류: {e}")

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
                    filled, executed, remaining = _is_order_filled(data)
                    if filled:
                        level.buy_filled = True
                        callback_flags['buy'].add(level.level)

                        # 체결 시간 가져오기
                        filled_time = data.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                        if 'T' in str(filled_time):
                            filled_time = filled_time.replace('T', ' ').split('.')[0].split('+')[0]

                        print(f"✅ [{level.level}차] 매수 체결 완료: {level.buy_price}원 / {filled_time}")
                        send_telegram_message(MSG_BUY_FILLED.format(
                            market=market, 
                            level=level.level, 
                            buy_price=level.buy_price, 
                            volume=level.volume,
                            filled_time=filled_time
                        ))

                        if status_callback:
                            status_callback(level.level, f"[{level.level}차] 매수 체결 ✅ / 매도 대기")

                        # 체결 상태 즉시 저장
                        persist_state()

                        # ✅ 모든 기존 주문 취소 (현재 체결 차수 제외)
                        cancel_count = 0
                        for lv in levels:
                            if lv.level == level.level:
                                continue
                            if lv.buy_uuid and not lv.buy_filled:
                                if cancel_order_by_uuid(lv.buy_uuid):
                                    cancel_count += 1
                                lv.buy_uuid = None
                            if lv.sell_uuid and not lv.sell_filled:
                                if cancel_order_by_uuid(lv.sell_uuid):
                                    cancel_count += 1
                                lv.sell_uuid = None
                        
                        if cancel_count > 0:
                            print(f"🚫 {cancel_count}개 주문 취소 완료")
                        persist_state()

                        # 📤/🛒 매도-매수 한 쌍을 안전하게 등록
                        next_idx = level.level
                        next_level = levels[next_idx] if next_idx < len(levels) else None
                        place_pair_orders(sell_target=level, buy_target=next_level)
                        persist_state()

                # ✅ 매도 체결 확인
                if level.sell_uuid and not level.sell_filled:
                    detail = _safe_get_order_detail(level.sell_uuid)
                    data = detail.get('data') or detail
                    filled, executed, remaining = _is_order_filled(data)
                    if filled:
                        level.sell_filled = True
                        callback_flags['sell'].add(level.level)

                        # ✅ 빗썸 수수료 반영 수익 계산
                        fee_rate = 0.0004

                        buy_cost = level.buy_price * (1 + fee_rate)
                        sell_income = level.sell_price * (1 - fee_rate)
                        profit = (sell_income - buy_cost) * level.volume

                        realized_profit += profit
                        strategy_info["realized_profit"] = realized_profit

                        # 체결 시간 가져오기
                        filled_time = data.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                        if 'T' in str(filled_time):
                            filled_time = filled_time.replace('T', ' ').split('.')[0].split('+')[0]

                        # 체결 이력 저장 (복구용)
                        trade_history.append({
                            "level": level.level,
                            "buy_price": level.buy_price,
                            "sell_price": level.sell_price,
                            "volume": level.volume,
                            "profit": profit,
                            "filled_time": filled_time,
                            "timestamp": time.time()
                        })

                        print(f"💰 [{level.level}차] 매도 체결 완료: {level.sell_price}원 / 수익 {profit:.0f}원 / {filled_time}")
                        send_telegram_message(MSG_SELL_FILLED.format(
                            market=market, 
                            level=level.level, 
                            sell_price=level.sell_price, 
                            volume=level.volume, 
                            profit=profit, 
                            realized_profit=realized_profit,
                            filled_time=filled_time
                        ))

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

                        # 체결 상태 즉시 저장
                        persist_state()

                        # ✅ 모든 기존 주문 취소 (현재 체결 차수 제외)
                        cancel_count = 0
                        for lv in levels:
                            if lv.level == level.level:
                                continue
                            if lv.buy_uuid and not lv.buy_filled:
                                if cancel_order_by_uuid(lv.buy_uuid):
                                    cancel_count += 1
                                lv.buy_uuid = None
                            if lv.sell_uuid and not lv.sell_filled:
                                if cancel_order_by_uuid(lv.sell_uuid):
                                    cancel_count += 1
                                lv.sell_uuid = None
                        
                        if cancel_count > 0:
                            print(f"🚫 {cancel_count}개 주문 취소 완료")
                        persist_state()

                        # 🛒/📤 매수-매도 한 쌍을 안전하게 등록 (현재차 매수, 이전차 매도)
                        prev_idx = level.level - 2
                        prev_level = levels[prev_idx] if prev_idx >= 0 else None
                        place_pair_orders(sell_target=prev_level, buy_target=level)
                        persist_state()

        except Exception as loop_error:
            print(f"⚠️ 루프 처리 중 오류 발생: {loop_error}")
            persist_state()

        # 헬스체크 실행 (주기적으로)
        health_check_counter += 1
        if health_check_counter >= health_check_interval:
            perform_health_check()
            health_check_counter = 0
        
        # 하트비트 기록 (주기적으로)
        heartbeat_counter += 1
        if heartbeat_counter >= heartbeat_interval:
            _write_heartbeat()
            heartbeat_counter = 0

        time.sleep(sleep_sec)
