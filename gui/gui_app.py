## File: gui/gui_app.py
# bithumbSplit GUI Application - Fixed Version

import os
import sys
import customtkinter as ctk
import threading
import time
from datetime import datetime
from tkinter import messagebox
import queue
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
if getattr(sys, 'frozen', False):
    base_path = Path(sys.executable).parent
else:
    base_path = Path(__file__).parent.parent

if str(base_path) not in sys.path:
    sys.path.insert(0, str(base_path))

from strategy.auto_trade import run_auto_trade
from utils.telegram import send_telegram_message
from api.api import cancel_all_orders, get_current_price
from shared.state import strategy_info

# CustomTkinter 설정
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# GUI 앱 생성
app = ctk.CTk()
app.title("bithumbSplit")

# 화면 크기 감지 및 창 크기 동적 설정
screen_width = app.winfo_screenwidth()
screen_height = app.winfo_screenheight()

# 화면 크기의 85%로 설정 (최소 600x700, 최대 700x1000)
window_width = min(max(int(screen_width * 0.4), 600), 700)
window_height = min(max(int(screen_height * 0.85), 700), 1000)

# 창을 화면 중앙에 배치
x = (screen_width - window_width) // 2
y = (screen_height - window_height) // 2

app.geometry(f"{window_width}x{window_height}+{x}+{y}")
app.minsize(600, 700)  # 최소 크기 설정

# 전역 변수
stop_flag = False
running_flag = False
strategy_summary_labels = {}
status_queue = queue.Queue()  # 스레드 간 통신을 위한 큐
current_buy_level = 0  # 현재 매수 차수
current_sell_level = 0  # 현재 매도 차수
label_status = None
current_level_label = None
status_text_label = None

def stop_condition():
    return stop_flag

realized_profit = 0.0

# 실시간 시세 표시용 변수
price_labels = {}

# 전략 정보 저장용 변수
def get_current_price_temp(coin):
    """임시 현재가 조회 함수 - 업비트 API 사용"""
    try:
        import requests
        market = f"KRW-{coin}"
        url = "https://api.upbit.com/v1/ticker"
        params = {"markets": market}
        
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        
        if data and len(data) > 0:
            return float(data[0]['trade_price'])
        return None
        
    except Exception as e:
        print(f"❌ {coin} 가격 조회 실패: {e}")
        return None

# 실시간 시세 업데이트 함수
def update_price_info():
    """실시간 시세 업데이트 함수 - 수정된 버전"""
    def loop():
        while True:
            try:
                # 현재 시간 업데이트
                now = datetime.now().strftime("%H:%M:%S")
                
                # 메인 스레드에서 안전하게 시간 업데이트
                def update_time():
                    if "time" in price_labels:
                        price_labels["time"].configure(text=f"⏱️ {now}")
                
                app.after(0, update_time)
                
                # 코인 가격 업데이트
                coins = ["BTC", "USDT", "XRP"]
                strategy_coin = strategy_info.get("market")
                if strategy_coin:
                    coins.append(strategy_coin)
                    
                for coin in coins:
                    try:
                        price = get_current_price_temp(coin)  # 임시 함수 사용
                        
                        def update_coin_price(c=coin, p=price):
                            if c in price_labels:
                                if p:
                                    price_labels[c].configure(text=f"{c}: {p:,.0f} KRW")
                                else:
                                    price_labels[c].configure(text=f"{c}: 조회 실패")
                        
                        app.after(0, update_coin_price)
                        
                        if coin == strategy_info.get("market"):
                            strategy_info["current_price"] = price
                            app.after(0, update_strategy_summary)

                    except Exception as e:
                        print(f"[ERROR] {coin} 가격 조회 중 오류: {e}")
                        
                        def update_error(c=coin):
                            if c in price_labels:
                                price_labels[c].configure(text=f"{c}: 오류")
                        
                        app.after(0, update_error)
                
            except Exception as e:
                print(f"[ERROR] 전체 가격 업데이트 오류: {e}")

            # 3초 대기
            time.sleep(3)
    
    # 데몬 스레드로 시작
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    print("[INFO] 실시간 가격 업데이트 스레드 시작됨")

# 전략 요약 정보 업데이트 함수
def update_strategy_summary():
    try:
        current = strategy_info.get("current_price", 0)
        start = strategy_info.get("start_price", 0)
        profit = strategy_info.get("realized_profit", 0)

        summary_labels["market"].configure(text=f"코인: {strategy_info['market']}")
        summary_labels["start_price"].configure(text=f"시작가: {start:,.0f} KRW")
        summary_labels["current_price"].configure(text=f"현재가: {current:,.0f} KRW")  # 추가
        summary_labels["profit"].configure(
            text=f"총 수익: {profit:,.0f} KRW", 
            text_color="green" if profit >= 0 else "red"
        )
    except Exception as e:
        print(f"[ERROR] update_strategy_summary: {e}")


def update_order_status(level, text):
    """주문 상태 업데이트 - 매수/매도 동시 표시"""
    try:
        # 큐에 업데이트 정보 추가
        status_queue.put(("order_status", level, text))
        # 메인 스레드에서 처리하도록 스케줄링
        app.after(0, process_status_updates)
    except Exception as e:
        print(f"[ERROR] update_order_status: {e}")

def process_status_updates():
    """큐에서 상태 업데이트 처리"""
    global current_buy_level, current_sell_level
    try:
        while not status_queue.empty():
            update_type, level, text = status_queue.get_nowait()
            
            if update_type == "order_status":
                # 매수/매도 상태 추적
                if "매수 주문" in text or "매수 체결" in text:
                    current_buy_level = level
                if "매도 주문" in text or "매도 체결" in text:
                    current_sell_level = level
                
                # 현재 차수 정보 표시
                def update_current_level():
                    # 매수 정보 표시
                    buy_info = f"🛒 {current_buy_level}차 매수" if current_buy_level > 0 else "🛒 매수 대기"
                    sell_info = f"📤 {current_sell_level}차 매도" if current_sell_level > 0 else "📤 매도 대기"
                    
                    current_level_label.configure(text=f"{buy_info}  |  {sell_info}")
                    
                    # 상태 텍스트 표시
                    status_text_label.configure(text=text)
                    
                    # 상태에 따라 색상 변경
                    if "매도 체결" in text:
                        status_text_label.configure(text_color="green")
                    elif "매수 체결" in text:
                        status_text_label.configure(text_color="orange")
                    elif "매수 주문" in text or "매도 주문" in text:
                        status_text_label.configure(text_color="yellow")
                    else:
                        status_text_label.configure(text_color="white")
                
                app.after(0, update_current_level)
                        
    except Exception as e:
        print(f"[ERROR] process_status_updates: {e}")

def initialize_order_cards(max_levels):
    """주문 상태 초기화 - 현재 차수만 표시하므로 불필요"""
    try:
        # 초기 상태 표시
        current_level_label.configure(text="🛒 매수 대기  |  📤 매도 대기")
        status_text_label.configure(text="⏳ 주문 상태를 기다리는 중...")
    except Exception as e:
        print(f"[ERROR] initialize_order_cards: {e}")

def start_strategy():
    """전략 시작"""
    global stop_flag, running_flag

    if running_flag:
        messagebox.showwarning("알림", "이미 전략이 실행 중입니다.")
        return

    # 입력값 파싱 및 기본 검증
    try:
        market = entry_market.get().strip().upper()
        start_price = float(entry_price.get())
        krw_amount = float(entry_amount.get())
        max_levels = int(entry_rounds.get())
        buy_gap = float(entry_buy_gap.get())
        sell_gap = float(entry_sell_gap.get())
        resume_level_str = entry_resume_level.get().strip()
        resume_level = int(resume_level_str) if resume_level_str else 0
    except ValueError:
        messagebox.showerror("입력 오류", "숫자 필드에 올바른 값을 입력해주세요.")
        return

    if not market:
        messagebox.showerror("입력 오류", "코인을 입력해주세요.")
        return
    if start_price <= 0:
        messagebox.showerror("입력 오류", "시작가는 0보다 커야 합니다.")
        return
    if krw_amount <= 0:
        messagebox.showerror("입력 오류", "매수금액은 0보다 커야 합니다.")
        return
    if max_levels <= 0:
        messagebox.showerror("입력 오류", "최대차수는 1 이상이어야 합니다.")
        return
    if buy_gap <= 0:
        messagebox.showerror("입력 오류", "매수 간격은 0보다 커야 합니다.")
        return
    if sell_gap <= 0:
        messagebox.showerror("입력 오류", "매도 간격은 0보다 커야 합니다.")
        return
    if resume_level < 0 or resume_level > max_levels:
        messagebox.showerror("입력 오류", f"재시작 차수는 0~{max_levels} 사이여야 합니다.")
        return

    estimated_cost = krw_amount * max_levels
    if estimated_cost > 10000000:  # 1000만원 이상
        if not messagebox.askokcancel(
            "확인",
            f"예상 총 비용: {estimated_cost:,.0f}원\n\n진행하시겠습니까?"
        ):
            return

    # 최종 실행 확인 (오입력/오클릭 방지)
    confirm_msg = (
        "전략을 시작하시겠습니까?\n\n"
        f"코인: {market}\n"
        f"시작가: {start_price:,.0f}원\n"
        f"매수금액: {krw_amount:,.0f}원\n"
        f"최대차수: {max_levels}차\n"
        f"매수간격: {buy_gap} ({buy_mode.get()})\n"
        f"매도간격: {sell_gap} ({sell_mode.get()})\n"
        f"재시작 차수: {resume_level if resume_level else '새 시작'}"
    )
    if not messagebox.askokcancel("전략 실행 확인", confirm_msg):
        return

    # 상태 플래그/버튼 업데이트
    stop_flag = False
    running_flag = True
    btn_start.configure(state="disabled")
    btn_stop.configure(state="normal")
    label_status.configure(text="🚀 전략 실행 중", text_color="green")

    def run_strategy_thread():
        """전략 실행 스레드"""
        global stop_flag, running_flag
        try:
            # 초기 상태 표시
            app.after(0, lambda: initialize_order_cards(max_levels))

            # 전략 메타 업데이트
            strategy_info["market"] = market
            strategy_info["start_price"] = start_price
            strategy_info["realized_profit"] = 0.0

            print(f"[DEBUG] 전략 실행 시작 - {market}, 시작가: {start_price}")

            run_auto_trade(
                start_price=start_price,
                krw_amount=krw_amount,
                max_levels=max_levels,
                market_code=market,
                buy_gap=buy_gap,
                buy_mode=buy_mode.get(),
                sell_gap=sell_gap,
                sell_mode=sell_mode.get(),
                stop_condition=stop_condition,
                sleep_sec=5,
                status_callback=update_order_status,
                summary_callback=update_strategy_summary,
                resume_level=resume_level,
            )

            if stop_flag:
                app.after(0, lambda: messagebox.showwarning("전략 중단", "사용자에 의해 전략이 중단되었습니다."))
                app.after(0, lambda: label_status.configure(text="🛑 전략 중단됨", text_color="red"))
            else:
                app.after(0, lambda: messagebox.showinfo("전략 완료", "전략이 성공적으로 완료되었습니다."))
                app.after(0, lambda: label_status.configure(text="✅ 전략 완료", text_color="gray"))
        except Exception as e:
            import traceback

            error_msg = f"전략 실행 중 오류 발생:\n{str(e)}"
            print(f"[ERROR] {error_msg}")
            print(f"[TRACEBACK] {traceback.format_exc()}")
            app.after(0, lambda: messagebox.showerror("오류", error_msg))
            app.after(0, lambda: label_status.configure(text="❌ 전략 오류", text_color="red"))
        finally:
            running_flag = False
            app.after(0, lambda: btn_start.configure(state="normal"))
            app.after(0, lambda: btn_stop.configure(state="disabled"))

    threading.Thread(target=run_strategy_thread, daemon=True).start()

def stop_strategy():
    """전략 중단"""
    global stop_flag
    
    if not running_flag:
        messagebox.showwarning("알림", "실행 중인 전략이 없습니다.")
        return

    if not messagebox.askokcancel("전략 중단 확인", "전략을 중단하고 모든 주문을 취소할까요?"):
        return
    
    stop_flag = True
    
    try:
        market = entry_market.get().strip().upper()
        full_market = f"KRW-{market}"
        
        # 모든 주문 취소
        cancel_all_orders(full_market)
        send_telegram_message(f"🛑 {market} 전략 중단 및 주문 전체 취소 완료")
        
        label_status.configure(text="🛑 전략 중단 중...", text_color="orange")
        current_level_label.configure(text="🛒 중단됨  |  📤 중단됨")
        status_text_label.configure(text="⛔ 전략이 중단되었습니다.", text_color="red")
            
    except Exception as e:
        error_msg = f"전략 중단 중 오류: {str(e)}"
        print(f"[ERROR] {error_msg}")
        send_telegram_message(f"⚠️ {error_msg}")
        messagebox.showerror("오류", error_msg)

# 정기적으로 상태 업데이트 처리
def periodic_update():
    """정기적인 업데이트 처리"""
    try:
        process_status_updates()
    except Exception as e:
        print(f"[ERROR] periodic_update: {e}")
    finally:
        app.after(100, periodic_update)  # 100ms마다 실행

# UI 구성 - 스크롤 가능한 메인 프레임
main_scrollable = ctk.CTkScrollableFrame(app)
main_scrollable.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
main_scrollable.grid_columnconfigure(0, weight=1)

# 앱 그리드 설정
app.grid_rowconfigure(0, weight=1)
app.grid_columnconfigure(0, weight=1)
        
### 실시간 시세 정보 표시
price_frame = ctk.CTkFrame(main_scrollable)
price_frame.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="ew")
price_frame.columnconfigure(0, weight=1)  # 수평 확장 설정

price_labels["time"] = ctk.CTkLabel(price_frame, text="⏱️ --:--:--", font=ctk.CTkFont(size=13))
price_labels["time"].pack(anchor="w", padx=10, pady=(5, 0))

for coin in ["BTC", "USDT", "XRP"]:
    price_labels[coin] = ctk.CTkLabel(price_frame, text=f"{coin}: -", font=ctk.CTkFont(size=13))
    price_labels[coin].pack(anchor="w", padx=10)

### 입력 UI 프레임
input_frame = ctk.CTkFrame(main_scrollable)
input_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
input_frame.columnconfigure(0, weight=1)

# 기본 설정 프레임
basic_frame = ctk.CTkFrame(input_frame)
basic_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
basic_frame.columnconfigure((0, 1, 2, 3), weight=1)

ctk.CTkLabel(basic_frame, text="기본 설정", font=ctk.CTkFont(size=14, weight="bold"))\
    .grid(row=0, column=0, columnspan=4, pady=(5, 10))

# 코인 / 시작가
ctk.CTkLabel(basic_frame, text="코인").grid(row=1, column=0, sticky="e", padx=5, pady=2)
entry_market = ctk.CTkEntry(basic_frame)
entry_market.grid(row=1, column=1, sticky="ew", padx=5, pady=2)

ctk.CTkLabel(basic_frame, text="시작가").grid(row=1, column=2, sticky="e", padx=5, pady=2)
entry_price = ctk.CTkEntry(basic_frame)
entry_price.grid(row=1, column=3, sticky="ew", padx=5, pady=2)

# 매수금액 / 최대차수
ctk.CTkLabel(basic_frame, text="매수금액").grid(row=2, column=0, sticky="e", padx=5, pady=2)
entry_amount = ctk.CTkEntry(basic_frame)
entry_amount.grid(row=2, column=1, sticky="ew", padx=5, pady=2)

ctk.CTkLabel(basic_frame, text="최대차수").grid(row=2, column=2, sticky="e", padx=5, pady=2)
entry_rounds = ctk.CTkEntry(basic_frame)
entry_rounds.grid(row=2, column=3, sticky="ew", padx=5, pady=2)

# 재시작 차수
ctk.CTkLabel(basic_frame, text="재시작 차수").grid(row=3, column=0, sticky="e", padx=5, pady=2)
entry_resume_level = ctk.CTkEntry(basic_frame)
entry_resume_level.grid(row=3, column=1, sticky="ew", padx=5, pady=2)
entry_resume_level.insert(0, "0")  # 기본값 0

ctk.CTkLabel(basic_frame, text="(0=새시작, N=N차부터)", font=ctk.CTkFont(size=10), text_color="gray")\
    .grid(row=3, column=2, columnspan=2, sticky="w", padx=5, pady=2)

# 간격 설정 프레임
gap_frame = ctk.CTkFrame(input_frame)
gap_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
gap_frame.columnconfigure((0, 1, 2, 3), weight=1)

ctk.CTkLabel(gap_frame, text="매매 간격 설정", font=ctk.CTkFont(size=14, weight="bold"))\
    .grid(row=0, column=0, columnspan=4, pady=(5, 10))

# 매수 간격 (기본 퍼센트, 기본값 0.2%)
buy_mode = ctk.StringVar(value="percent")
ctk.CTkLabel(gap_frame, text="매수 간격").grid(row=1, column=0, sticky="e", padx=5, pady=2)
entry_buy_gap = ctk.CTkEntry(gap_frame)
entry_buy_gap.insert(0, "0.2")
entry_buy_gap.grid(row=1, column=1, sticky="ew", padx=5, pady=2)

frame_buy_mode = ctk.CTkFrame(gap_frame)
frame_buy_mode.grid(row=1, column=2, columnspan=2, sticky="ew", padx=5, pady=2)
ctk.CTkRadioButton(frame_buy_mode, text="퍼센트", variable=buy_mode, value="percent").pack(side="left", padx=4)
ctk.CTkRadioButton(frame_buy_mode, text="금액(원)", variable=buy_mode, value="price").pack(side="left", padx=4)

# 매도 간격 (기본 퍼센트, 기본값 0.3%)
sell_mode = ctk.StringVar(value="percent")
ctk.CTkLabel(gap_frame, text="매도 간격").grid(row=2, column=0, sticky="e", padx=5, pady=2)
entry_sell_gap = ctk.CTkEntry(gap_frame)
entry_sell_gap.insert(0, "0.3")
entry_sell_gap.grid(row=2, column=1, sticky="ew", padx=5, pady=2)

frame_sell_mode = ctk.CTkFrame(gap_frame)
frame_sell_mode.grid(row=2, column=2, columnspan=2, sticky="ew", padx=5, pady=2)
ctk.CTkRadioButton(frame_sell_mode, text="퍼센트", variable=sell_mode, value="percent").pack(side="left", padx=4)
ctk.CTkRadioButton(frame_sell_mode, text="금액(원)", variable=sell_mode, value="price").pack(side="left", padx=4)

# 실행/중단 버튼 섹션
button_frame = ctk.CTkFrame(input_frame)
button_frame.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="ew")
button_frame.columnconfigure((0, 1), weight=1)

btn_start = ctk.CTkButton(button_frame, text="🚀 전략 실행", command=start_strategy, 
                         fg_color="#28a745", hover_color="#218838", height=45, 
                         font=ctk.CTkFont(size=14, weight="bold"))
btn_stop = ctk.CTkButton(button_frame, text="🛑 전략 중단", command=stop_strategy, 
                        fg_color="#dc3545", hover_color="#c82333", state="disabled", height=45,
                        font=ctk.CTkFont(size=14, weight="bold"))

btn_start.grid(row=0, column=0, pady=10, sticky="ew", padx=(10, 5))
btn_stop.grid(row=0, column=1, pady=10, sticky="ew", padx=(5, 10))

### 2. 전략 현황 카드
summary_frame = ctk.CTkFrame(main_scrollable)
summary_frame.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="ew")
summary_frame.columnconfigure(0, weight=1)

# 전략 현황 정보 라벨
ctk.CTkLabel(summary_frame, text="📈 전략 현황", font=ctk.CTkFont(size=16, weight="bold"))\
    .grid(row=0, column=0, pady=(10, 5))

# 전략 현황 정보를 카드 형태로 배치
summary_labels = {}

# 첫 번째 행: 코인
info_frame1 = ctk.CTkFrame(summary_frame)
info_frame1.grid(row=1, column=0, sticky="ew", padx=10, pady=2)

summary_labels["market"] = ctk.CTkLabel(info_frame1, text="코인: -", font=ctk.CTkFont(size=14, weight="bold"))
summary_labels["market"].pack(side="left", padx=10, pady=8)

# 두 번째 행: 시작가
info_frame_start = ctk.CTkFrame(summary_frame)
info_frame_start.grid(row=2, column=0, sticky="ew", padx=10, pady=2)

summary_labels["start_price"] = ctk.CTkLabel(info_frame_start, text="시작가: -", font=ctk.CTkFont(size=14))
summary_labels["start_price"].pack(side="left", padx=10, pady=8)

# 세 번째 행: 현재가
info_frame_current = ctk.CTkFrame(summary_frame)
info_frame_current.grid(row=3, column=0, sticky="ew", padx=10, pady=2)

summary_labels["current_price"] = ctk.CTkLabel(info_frame_current, text="현재가: -", font=ctk.CTkFont(size=14))
summary_labels["current_price"].pack(side="left", padx=10, pady=8)

# 네 번째 행: 수익액
info_frame_profit = ctk.CTkFrame(summary_frame)
info_frame_profit.grid(row=4, column=0, sticky="ew", padx=10, pady=2)

summary_labels["profit"] = ctk.CTkLabel(info_frame_profit, text="총 수익: -", font=ctk.CTkFont(size=14, weight="bold"))
summary_labels["profit"].pack(side="left", padx=10, pady=8)

### 3. 현재 차수 상태 카드
current_order_frame = ctk.CTkFrame(main_scrollable)
current_order_frame.grid(row=3, column=0, padx=10, pady=(5, 10), sticky="ew")
current_order_frame.columnconfigure(0, weight=1)

# 프레임 제목
ctk.CTkLabel(current_order_frame, text="📊 현재 주문 상태", font=ctk.CTkFont(size=16, weight="bold"))\
    .grid(row=0, column=0, pady=(10, 10))

label_status = ctk.CTkLabel(
    current_order_frame,
    text="⏸️ 대기 중",
    font=ctk.CTkFont(size=14, weight="bold"),
    text_color="gray",
)
label_status.grid(row=1, column=0, pady=(0, 8))

current_level_label = ctk.CTkLabel(
    current_order_frame,
    text="🛒 매수 대기  |  📤 매도 대기",
    font=ctk.CTkFont(size=14, weight="bold"),
)
current_level_label.grid(row=2, column=0, pady=(0, 6))

status_text_label = ctk.CTkLabel(
    current_order_frame,
    text="⏳ 주문 상태를 기다리는 중...",
    font=ctk.CTkFont(size=13),
)
status_text_label.grid(row=3, column=0, pady=(0, 10))

# 정기 업데이트 시작
periodic_update()

# 실시간 시세 정보 업데이트 시작
update_price_info()

if __name__ == "__main__":
    app.mainloop()