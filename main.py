# bithumbSplit/main.py
# 무한 반복형 자동매매 전략 실행 (auto_trade.py 기반)

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
base_path = Path(__file__).parent
if str(base_path) not in sys.path:
    sys.path.insert(0, str(base_path))

from strategy.auto_trade import run_auto_trade
from utils.telegram import send_telegram_message

if __name__ == '__main__':
    print("📈 무한 반복 매수-매도 전략 실행 시작")

    market_code = input("마켓 코드를 입력하세요 (예: USDT, BTC): ").strip().upper()
    start_price = float(input("시작 기준 가격을 입력하세요 (예: 1430): ").strip())
    krw_amount = float(input("회차당 매수 금액 (KRW)을 입력하세요 (예: 5000): ").strip())
    max_levels = int(input("매수 레벨 개수를 입력하세요 (예: 3): ").strip())

    # ✅ 매수 간격 입력
    buy_mode = input("매수 간격 단위를 선택하세요 (percent/price): ").strip().lower()
    buy_gap = float(input(f"매수 간격 값을 입력하세요 ({'%' if buy_mode == 'percent' else '원'}): ").strip())

    # ✅ 매도 간격 입력
    sell_mode = input("매도 간격 단위를 선택하세요 (percent/price): ").strip().lower()
    sell_gap = float(input(f"매도 간격 값을 입력하세요 ({'%' if sell_mode == 'percent' else '원'}): ").strip())

    send_telegram_message(
        f"🚀 자동매매 전략 시작\n<b>{market_code}</b>\n기준가: {start_price}원\n"
        f"매수간격: {buy_gap}{'%' if buy_mode == 'percent' else '원'}\n"
        f"매도간격: {sell_gap}{'%' if sell_mode == 'percent' else '원'}\n"
        f"회차당 금액: {krw_amount}원\n레벨: {max_levels}")

    run_auto_trade(
        start_price=start_price,
        krw_amount=krw_amount,
        max_levels=max_levels,
        market_code=market_code,
        buy_gap=buy_gap,
        buy_mode=buy_mode,
        sell_gap=sell_gap,
        sell_mode=sell_mode
    )