# watchdog.py
# 자동매매 프로세스 감시 및 자동 재시작 스크립트
# 30초마다 heartbeat 파일을 확인하고, stale하면 프로세스 재시작
# 1시간마다 진행 현황 요약 메시지 전송 (주문 리스트 포함)

import os
import json
import time
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트
if getattr(sys, 'frozen', False):
    base_path = Path(sys.executable).parent
else:
    base_path = Path(__file__).parent

if str(base_path) not in sys.path:
    sys.path.insert(0, str(base_path))

from utils.telegram import send_telegram_message
from api.api import get_order_list

LOGS_DIR = os.path.join(base_path, 'logs')
CONFIG_DIR = os.path.join(base_path, 'config')
MARKETS_CONFIG_FILE = os.path.join(CONFIG_DIR, 'markets_config.json')
HEARTBEAT_TIMEOUT = 120  # 2분 이상 응답 없으면 재시작
CHECK_INTERVAL = 30  # 30초마다 체크
SUMMARY_INTERVAL = 3600  # 1시간마다 요약 전송 (초)

# 시작할 자동매매 프로세스 정보
WORKER_SCRIPT = os.path.join(base_path, 'worker.py')
DEFAULT_MARKETS = ['BTC', 'USDT', 'XRP']  # 기본 모니터링 코인들

# Watchdog 시작 시간
WATCHDOG_START_TIME = datetime.now()

# 활성 프로세스 저장 (market -> PID)
active_processes = {}

def load_markets_config():
    """markets_config.json에서 마켓 설정 로드"""
    try:
        if not os.path.exists(MARKETS_CONFIG_FILE):
            print(f"⚠️  markets_config.json 파일을 찾을 수 없습니다.")
            print(f"   경로: {MARKETS_CONFIG_FILE}")
            print(f"   GUI에서 '설정 저장 & 자동매매 시작'을 클릭해주세요.")
            return {}
        
        with open(MARKETS_CONFIG_FILE, 'r', encoding='utf-8') as f:
            configs = json.load(f)
        
        print(f"✅ markets_config.json 로드 완료: {list(configs.keys())}")
        return configs
    except Exception as e:
        print(f"⚠️ 설정 파일 로드 실패: {e}")
        return {}

def get_heartbeat_file(market):
    """마켓별 하트비트 파일 경로"""
    return os.path.join(LOGS_DIR, f'heartbeat_KRW_{market}.json')

def read_heartbeat(market):
    """하트비트 파일 읽기"""
    try:
        hb_file = get_heartbeat_file(market)
        if not os.path.exists(hb_file):
            return None
        
        with open(hb_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"⚠️ [{market}] 하트비트 읽기 실패: {e}")
        return None

def is_heartbeat_stale(market):
    """하트비트가 stale인지 확인 (타임스탐프 기반)"""
    hb = read_heartbeat(market)
    if not hb:
        return True  # 파일 없으면 stale
    
    try:
        ts_str = hb.get('timestamp', '')
        ts = datetime.fromisoformat(ts_str)
        elapsed = (datetime.now() - ts).total_seconds()
        
        if elapsed > HEARTBEAT_TIMEOUT:
            print(f"⚠️ [{market}] 하트비트 stale 감지: {elapsed:.0f}초 응답 없음")
            return True
        return False
    except Exception as e:
        print(f"⚠️ [{market}] 타임스탐프 파싱 실패: {e}")
        return True

def restart_worker(market, config):
    """워커 프로세스 재시작"""
    try:
        print(f"🔄 [{market}] 프로세스 재시작 중...")
        
        # Windows에서 python 실행파일 경로
        python_exe = sys.executable
        
        # 설정에서 파라미터 추출
        start_price = config.get('start_price', 100000)
        krw_amount = config.get('krw_amount', 1000000)
        max_levels = config.get('max_levels', 60)
        resume_level = config.get('resume', 0)
        buy_gap = config.get('buy_gap', 0.2)
        sell_gap = config.get('sell_gap', 0.3)
        
        # 워커 스크립트 실행 (별도 프로세스로)
        cmd = [
            python_exe, WORKER_SCRIPT,
            '--market', market,
            '--start-price', str(int(start_price)),
            '--krw-amount', str(int(krw_amount)),
            '--max-levels', str(int(max_levels)),
            '--buy-gap', str(buy_gap),
            '--sell-gap', str(sell_gap),
            '--resume-level', str(int(resume_level)),
        ]
        
        # 백그라운드에서 실행
        if sys.platform == 'win32':
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        active_processes[market] = proc.pid
        print(f"✅ [{market}] 프로세스 재시작 완료 (PID: {proc.pid})")
        send_telegram_message(f"🔄 [{market}] 워커 프로세스 재시작됨 (하트비트 타임아웃)")
        return True
    except Exception as e:
        print(f"❌ [{market}] 프로세스 재시작 실패: {e}")
        send_telegram_message(f"❌ [{market}] 워커 재시작 실패: {e}")
        return False

def check_and_restart(markets_config):
    """하트비트 확인 및 필요 시 재시작"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    
    # 모니터링할 마켓 결정 (enabled=True만)
    if markets_config:
        markets = [m for m, cfg in markets_config.items() if cfg.get('enabled', True)]
    else:
        markets = []

    if not markets:
        print("⚠️ 활성화된 마켓이 없습니다. GUI에서 on/off를 설정하세요.")
        return
    
    print(f"\n📍 모니터링 마켓: {', '.join(markets)}")
    print(f"⏱️ 타임아웃: {HEARTBEAT_TIMEOUT}초")
    print(f"📊 체크 주기: {CHECK_INTERVAL}초")
    print(f"📈 정기 리포트: {SUMMARY_INTERVAL//3600}시간마다\n")
    
    # 초기 워커 시작 (enabled만)
    for market in markets:
        if market in markets_config and markets_config[market].get('enabled', True):
            restart_worker(market, markets_config[market])
        else:
            print(f"⚠️ [{market}] 설정이 없거나 비활성화되었습니다.")
    
    last_summary_time = time.time()
    
    while True:
        try:
            current_time = time.time()
            
            # 1시간마다 정기 리포트 전송
            if current_time - last_summary_time >= SUMMARY_INTERVAL:
                send_summary_report(markets, markets_config)
                last_summary_time = current_time
            
            for market in markets:
                if is_heartbeat_stale(market):
                    hb = read_heartbeat(market)
                    if hb:
                        profit = hb.get('realized_profit', 0)
                        pending = hb.get('pending_orders', 0)
                        print(f"\n⚠️ [{market}] 응답 없음 (누적수익: {profit:,.0f}원, 미체결: {pending}개)")
                    
                    # 재시작
                    if market in markets_config and markets_config[market].get('enabled', True):
                        restart_worker(market, markets_config[market])
                else:
                    hb = read_heartbeat(market)
                    if hb:
                        print(f"✅ [{market}] 정상 작동 (수익: {hb.get('realized_profit', 0):,.0f}원)")
        
        except Exception as e:
            print(f"⚠️ Watchdog 오류: {e}")
        
        # 지정된 주기로 체크
        time.sleep(CHECK_INTERVAL)

def log_status(markets):
    """현재 상태 로깅"""
    print(f"\n{'='*60}")
    print(f"🔍 Watchdog 상태 확인 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    for market in markets:
        hb = read_heartbeat(market)
        if hb:
            print(f"\n📊 {market}:")
            print(f"   타임스탐프: {hb.get('timestamp', 'N/A')}")
            print(f"   상태: {hb.get('status', 'N/A')}")
            print(f"   누적수익: {hb.get('realized_profit', 0):,.0f}원")
            print(f"   현재 차수: {hb.get('last_buy_level', 0)}차")
            print(f"   미체결 주문: {hb.get('pending_orders', 0)}개")
        else:
            print(f"\n📊 {market}: 하트비트 파일 없음")

def send_summary_report(markets, markets_config):
    """1시간마다 진행 현황 요약 메시지 전송 (주문 리스트 포함)"""
    try:
        uptime = datetime.now() - WATCHDOG_START_TIME
        hours = int(uptime.total_seconds() // 3600)
        minutes = int((uptime.total_seconds() % 3600) // 60)
        
        summary = f"📊 [Watchdog 정기 리포트]\n⏱️ 운영 시간: {hours}시간 {minutes}분\n\n"
        
        total_profit = 0
        active_markets = 0
        issues = []
        
        for market in markets:
            hb = read_heartbeat(market)
            if hb:
                active_markets += 1
                profit = hb.get('realized_profit', 0)
                total_profit += profit
                level = hb.get('last_buy_level', 0)
                pending = hb.get('pending_orders', 0)
                
                summary += f"✅ {market}:\n"
                summary += f"   현재 차수: {level}차\n"
                summary += f"   누적 수익: {profit:,.0f}원\n"
                summary += f"   미체결 주문: {pending}개\n"
                
                # 실제 주문 리스트 조회 및 추가
                try:
                    order_list = get_order_list(market=f'KRW-{market}', limit=100)
                    if isinstance(order_list, list) and order_list:
                        summary += f"   📋 주문 목록:\n"
                        for order in order_list[:5]:  # 최근 5개만 표시
                            side = "🛒 매수" if order.get('side') == 'bid' else "📤 매도"
                            price = float(order.get('price', 0))
                            volume = float(order.get('volume', 0))
                            created = order.get('created_at', '')
                            if 'T' in str(created):
                                created = created.split('T')[1].split('.')[0]
                            summary += f"      {side} {price:,.0f}원 x {volume:.8f} ({created})\n"
                        if len(order_list) > 5:
                            summary += f"      ... 외 {len(order_list) - 5}개\n"
                    else:
                        summary += f"   📋 주문 목록: 없음\n"
                except Exception as e:
                    summary += f"   ⚠️ 주문 조회 실패: {e}\n"
                
                summary += "\n"
                
                # stale 여부 확인
                if is_heartbeat_stale(market):
                    issues.append(f"⚠️ {market} - 응답 없음")
            else:
                issues.append(f"❌ {market} - 하트비트 없음")
        
        summary += f"💰 총 누적 수익: {total_profit:,.0f}원\n"
        summary += f"📍 활성 마켓: {active_markets}/{len(markets)}개\n"
        
        if issues:
            summary += f"\n⚠️ 이슈:\n" + "\n".join(issues)
        else:
            summary += f"\n✨ 모든 마켓 정상 운영 중"
        
        send_telegram_message(summary)
        print(f"\n📤 정기 리포트 전송:\n{summary}")
        
    except Exception as e:
        print(f"⚠️ 정기 리포트 전송 실패: {e}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="자동매매 워커 Watchdog")
    parser.add_argument('--status', action='store_true', help="현재 상태만 확인")
    args = parser.parse_args()
    
    # 설정 로드
    markets_config = load_markets_config()
    
    if args.status:
        markets = list(markets_config.keys()) if markets_config else DEFAULT_MARKETS
        log_status(markets)
    else:
        print("🚀 Watchdog 시작...\n")
        
        if not markets_config:
            print("⚠️ markets_config.json 설정 파일을 찾을 수 없습니다!")
            print("👉 다음 단계를 따르세요:")
            print("   1. GUI 프로그램 실행 (python main.py)")
            print("   2. BTC, USDT, XRP 설정 입력")
            print("   3. '설정 저장 & 자동매매 시작' 버튼 클릭")
            print("   4. start_watchdog.bat 다시 실행\n")
            sys.exit(1)
        
        try:
            check_and_restart(markets_config)
        except KeyboardInterrupt:
            print("\n\n🛑 Watchdog 종료됨")
            sys.exit(0)
