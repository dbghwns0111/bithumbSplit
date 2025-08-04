## File: gui/gui_app.py
# AutoBitTrade GUI Application - Fixed Version

import os
import sys
import customtkinter as ctk
import threading
import time
from datetime import datetime
from tkinter import messagebox
import queue

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.auto_trade import run_auto_trade
from utils.telegram import send_telegram_message
from api.api import cancel_all_orders, get_current_price
from shared.state import strategy_info

# CustomTkinter 설정
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# GUI 앱 생성
app = ctk.CTk()
app.title("AutoBitTrade")
app.geometry("600x1000")

# 전역 변수
stop_flag = False
running_flag = False
order_status_cards = {}  # 카드뷰 상태 저장
strategy_summary_labels = {}
status_queue = queue.Queue()  # 스레드 간 통신을 위한 큐

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
    """주문 상태 업데이트 - 메인 스레드에서 안전하게 실행"""
    try:
        # 큐에 업데이트 정보 추가
        status_queue.put(("order_status", level, text))
        # 메인 스레드에서 처리하도록 스케줄링
        app.after(0, process_status_updates)
    except Exception as e:
        print(f"[ERROR] update_order_status: {e}")

def process_status_updates():
    """큐에서 상태 업데이트 처리"""
    try:
        while not status_queue.empty():
            update_type, level, text = status_queue.get_nowait()
            
            if update_type == "order_status":
                # 주문 상태 카드 업데이트
                if level in order_status_cards:
                    label = order_status_cards[level]["label"]
                    
                    # 매도 체결 시 수익 계산
                    if "매도 체결" in text:
                        try:
                            # 수익 계산 로직
                            parts = text.split()
                            if len(parts) >= 4:
                                price_str = parts[3].replace("원", "").replace(",", "")
                                price = float(price_str)
                                
                                # 기존 매수 가격 찾기
                                current_text = label.cget("text")
                                if "매수 체결" in current_text:
                                    buy_parts = current_text.split()
                                    if len(buy_parts) >= 4:
                                        buy_price_str = buy_parts[3].replace("원", "").replace(",", "")
                                        buy_price = float(buy_price_str)
                                        
                                        # 수익 계산 (간단한 예시)
                                        fee_rate = 0.0008  # 매도, 매수 수수료 0.04% -> 총 0.08%
                                        profit_rate = ((price * (1 - fee_rate)) - (buy_price * (1 + fee_rate))) / (buy_price * (1 + fee_rate)) * 100

                                        label.configure(
                                            text=f"[{level}차] 매도 체결 ✅\n수익률: {profit_rate:+.2f}%",
                                            text_color="green" if profit_rate >= 0 else "red"
                                        )
                                    else:
                                        label.configure(text=text, text_color="blue")
                                else:
                                    label.configure(text=text, text_color="blue")
                        except Exception as e:
                            print(f"[ERROR] 매도 체결 처리 중 오류: {e}")
                            label.configure(text=text, text_color="blue")
                    
                    # 매수 체결
                    elif "매수 체결" in text:
                        label.configure(text=text, text_color="orange")
                    
                    # 매수 주문
                    elif "매수 주문" in text:
                        label.configure(text=text, text_color="yellow")
                    
                    # 매도 주문
                    elif "매도 주문" in text:
                        label.configure(text=text, text_color="cyan")
                    
                    # 기타
                    else:
                        label.configure(text=text)
                        
    except Exception as e:
        print(f"[ERROR] process_status_updates: {e}")

def start_strategy():
    """전략 시작"""
    global stop_flag, running_flag
    
    if running_flag:
        messagebox.showwarning("알림", "이미 전략이 실행 중입니다.")
        return
        
    # 입력값 검증
    try:
        market = entry_market.get().strip().upper()
        start_price = float(entry_price.get())
        krw_amount = float(entry_amount.get())
        max_levels = int(entry_rounds.get())
        buy_gap = float(entry_buy_gap.get())
        sell_gap = float(entry_sell_gap.get())
        
        if not market or start_price <= 0 or krw_amount <= 0 or max_levels <= 0:
            messagebox.showerror("입력 오류", "모든 필드를 올바르게 입력해주세요.")
            return
            
    except ValueError:
        messagebox.showerror("입력 오류", "숫자 필드에 올바른 값을 입력해주세요.")
        return

    def run_strategy():
        """전략 실행 스레드"""
        global stop_flag, running_flag
        
        try:
            stop_flag = False
            running_flag = True
            
            # UI 상태 업데이트
            app.after(0, lambda: btn_start.configure(state="disabled"))
            app.after(0, lambda: btn_stop.configure(state="normal"))
            app.after(0, lambda: label_status.configure(text="전략 실행 중...", text_color="green"))
            
            # 전략 정보 저장
            strategy_info.update({
                "market": market,
                "start_price": start_price,
                "krw_amount": krw_amount,
                "max_levels": max_levels,
                "current_price": start_price,
                "realized_profit": 0.0
            })
            
            # UI 업데이트
            app.after(0, update_strategy_summary)
            
            # 주문 상태 카드 초기화
            app.after(0, lambda: initialize_order_cards(max_levels))
            
            print(f"[DEBUG] 전략 실행 시작 - {market}, 시작가: {start_price}")
            
            # 전략 실행
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
                summary_callback=update_strategy_summary
            )
            
            # 전략 종료 처리
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
            # UI 상태 복원
            running_flag = False
            app.after(0, lambda: btn_start.configure(state="normal"))
            app.after(0, lambda: btn_stop.configure(state="disabled"))
    
    # 전략 실행 스레드 시작
    threading.Thread(target=run_strategy, daemon=True).start()

def initialize_order_cards(max_levels):
    """주문 상태 카드 초기화 (개선된 디자인)"""
    try:
        # 기존 카드 제거
        for widget in status_scroll_container.winfo_children():
            widget.destroy()
        
        order_status_cards.clear()
        
        # 새 카드 생성
        for i in range(max_levels):
            level = i + 1
            card = ctk.CTkFrame(status_scroll_container)
            card.grid(row=i, column=0, sticky="we", padx=5, pady=3)
            
            # 카드 내부 레이아웃
            card_inner = ctk.CTkFrame(card)
            card_inner.pack(fill="both", expand=True, padx=8, pady=8)
            
            # 차수 라벨
            level_label = ctk.CTkLabel(card_inner, text=f"{level}차", 
                                     font=ctk.CTkFont(size=12, weight="bold"),
                                     width=40)
            level_label.pack(side="left", padx=(0, 10))
            
            # 상태 라벨
            label = ctk.CTkLabel(card_inner, text="⏳ 대기 중...", anchor="w",
                               font=ctk.CTkFont(size=12))
            label.pack(side="left", fill="x", expand=True)
            
            order_status_cards[level] = {"frame": card, "label": label}
            
    except Exception as e:
        print(f"[ERROR] initialize_order_cards: {e}")

def stop_strategy():
    """전략 중단"""
    global stop_flag
    
    if not running_flag:
        messagebox.showwarning("알림", "실행 중인 전략이 없습니다.")
        return
    
    stop_flag = True
    
    try:
        market = entry_market.get().strip().upper()
        full_market = f"KRW-{market}"
        
        # 모든 주문 취소
        cancel_all_orders(full_market)
        send_telegram_message(f"🛑 {market} 전략 중단 및 주문 전체 취소 완료")
        
        label_status.configure(text="🛑 전략 중단 중...", text_color="orange")
        
        # 주문 상태 카드 업데이트
        for level, card in order_status_cards.items():
            card["label"].configure(text=f"{level}차 ⛔ 전략 중단됨", text_color="gray")
            
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
        
# UI 구성
### 실시간 시세 정보 표시
price_frame = ctk.CTkFrame(app)
price_frame.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="ew")
price_frame.columnconfigure(0, weight=1)  # 수평 확장 설정

price_labels["time"] = ctk.CTkLabel(price_frame, text="⏱️ --:--:--", font=ctk.CTkFont(size=13))
price_labels["time"].pack(anchor="w", padx=10, pady=(5, 0))

for coin in ["BTC", "USDT", "XRP"]:
    price_labels[coin] = ctk.CTkLabel(price_frame, text=f"{coin}: -", font=ctk.CTkFont(size=13))
    price_labels[coin].pack(anchor="w", padx=10)

### 입력 UI 프레임
input_frame = ctk.CTkFrame(app)
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

# 간격 설정 프레임
gap_frame = ctk.CTkFrame(input_frame)
gap_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
gap_frame.columnconfigure((0, 1, 2, 3), weight=1)

ctk.CTkLabel(gap_frame, text="매매 간격 설정", font=ctk.CTkFont(size=14, weight="bold"))\
    .grid(row=0, column=0, columnspan=4, pady=(5, 10))

# 매수 간격
buy_mode = ctk.StringVar(value="price")
ctk.CTkLabel(gap_frame, text="매수 간격").grid(row=1, column=0, sticky="e", padx=5, pady=2)
entry_buy_gap = ctk.CTkEntry(gap_frame)
entry_buy_gap.grid(row=1, column=1, sticky="ew", padx=5, pady=2)

frame_buy_mode = ctk.CTkFrame(gap_frame)
frame_buy_mode.grid(row=1, column=2, columnspan=2, sticky="ew", padx=5, pady=2)
ctk.CTkRadioButton(frame_buy_mode, text="퍼센트", variable=buy_mode, value="percent").pack(side="left", padx=4)
ctk.CTkRadioButton(frame_buy_mode, text="금액(원)", variable=buy_mode, value="price").pack(side="left", padx=4)

# 매도 간격
sell_mode = ctk.StringVar(value="price")
ctk.CTkLabel(gap_frame, text="매도 간격").grid(row=2, column=0, sticky="e", padx=5, pady=2)
entry_sell_gap = ctk.CTkEntry(gap_frame)
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
summary_frame = ctk.CTkFrame(app)
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

### 3. 주문 상태 스크롤 카드뷰
status_scroll_container = ctk.CTkScrollableFrame(app, label_text="📋 주문 상태", 
                                               label_font=ctk.CTkFont(size=16, weight="bold"))
status_scroll_container.grid(row=3, column=0, padx=10, pady=(5, 10), sticky="nsew")
status_scroll_container.grid_columnconfigure(0, weight=1)

### 4. 전략 상태 출력
status_frame = ctk.CTkFrame(app)
status_frame.grid(row=4, column=0, padx=10, pady=(0, 10), sticky="ew")

label_status = ctk.CTkLabel(status_frame, text="⏳ 전략 상태: 대기 중", 
                          font=ctk.CTkFont(size=16, weight="bold"))
label_status.pack(pady=15)

# 메인 윈도우 레이아웃 확장 설정
app.grid_rowconfigure(3, weight=1)  # 스크롤 영역이 확장되도록
app.grid_columnconfigure(0, weight=1)

# 정기 업데이트 시작
periodic_update()

# 실시간 시세 정보 업데이트 시작
update_price_info()

if __name__ == "__main__":
    app.mainloop()