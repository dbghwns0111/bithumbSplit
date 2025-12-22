# worker.py
# CLI 기반 자동매매 워커 (GUI 없음, 서버에서 24/7 실행용)

import sys
import argparse
import json
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
if getattr(sys, 'frozen', False):
    base_path = Path(sys.executable).parent
else:
    base_path = Path(__file__).parent

if str(base_path) not in sys.path:
    sys.path.insert(0, str(base_path))

from strategy.auto_trade import run_auto_trade
from utils.telegram import send_telegram_message

def load_config(market_code):
    """설정 파일에서 마켓별 매매 설정 로드"""
    try:
        config_file = base_path / 'config' / f'strategy_{market_code}.json'
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️ 설정 파일 로드 실패: {e}")
    
    # 기본값 반환
    return {
        'start_price': 100000,
        'krw_amount': 1000000,
        'max_levels': 60,
        'buy_gap': 0.2,
        'buy_mode': 'percent',
        'sell_gap': 0.3,
        'sell_mode': 'percent',
    }

def main():
    parser = argparse.ArgumentParser(description='bithumbSplit 자동매매 워커')
    parser.add_argument('--market', default='BTC', help='코인 (기본값: BTC)')
    parser.add_argument('--start-price', type=float, help='시작가')
    parser.add_argument('--krw-amount', type=float, help='매수금액')
    parser.add_argument('--max-levels', type=int, help='최대차수')
    parser.add_argument('--buy-gap', type=float, help='매수 간격')
    parser.add_argument('--sell-gap', type=float, help='매도 간격')
    parser.add_argument('--resume-level', type=int, default=0, help='재시작 차수 (0=새시작)')
    
    args = parser.parse_args()
    market = args.market.upper()
    
    # 설정 로드
    config = load_config(market)
    
    # 명령줄 인자로 오버라이드
    if args.start_price:
        config['start_price'] = args.start_price
    if args.krw_amount:
        config['krw_amount'] = args.krw_amount
    if args.max_levels:
        config['max_levels'] = args.max_levels
    if args.buy_gap:
        config['buy_gap'] = args.buy_gap
    if args.sell_gap:
        config['sell_gap'] = args.sell_gap
    
    print(f"""
╔════════════════════════════════════════════╗
║   bithumbSplit 자동매매 워커 시작         ║
╠════════════════════════════════════════════╣
║ 📍 코인: {market:15} 💰 시작가: {config['start_price']:>12,.0f}원 ║
║ 📊 매수금액: {config['krw_amount']:>12,.0f}원 🔢 최대차수: {config['max_levels']:>3}차 ║
║ 📈 매수간격: {config['buy_gap']:>5.2f} ({config['buy_mode']:<7}) 📉 매도간격: {config['sell_gap']:>5.2f} ({config['sell_mode']:<7}) ║
║ 🔄 재시작 차수: {args.resume_level:3}차                              ║
╚════════════════════════════════════════════╝
    """)
    
    try:
        send_telegram_message(
            f"🚀 [워커 시작]\n"
            f"📍 코인: {market}\n"
            f"💰 시작가: {config['start_price']:,.0f}원\n"
            f"📊 최대차수: {config['max_levels']}차"
        )
        
        run_auto_trade(
            start_price=config['start_price'],
            krw_amount=config['krw_amount'],
            max_levels=config['max_levels'],
            market_code=market,
            buy_gap=config['buy_gap'],
            buy_mode=config['buy_mode'],
            sell_gap=config['sell_gap'],
            sell_mode=config['sell_mode'],
            sleep_sec=5,
            resume_level=args.resume_level,
        )
    except KeyboardInterrupt:
        print("\n\n🛑 워커 종료됨")
        send_telegram_message(f"🛑 [{market}] 워커 종료")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        send_telegram_message(f"❌ [{market}] 워커 오류: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
