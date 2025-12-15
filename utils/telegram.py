# bitsplit/utils/telegram.py
# 텔레그램 알림 전송 유틸리티

import os
import requests
from dotenv import load_dotenv

# .env 파일에서 토큰과 채팅 ID 로드
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_message(message):
    """
    텔레그램 메시지 전송 함수
    :param message: 전송할 문자열 메시지
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, data=data)
        if response.status_code != 200:
            print(f"❌ 텔레그램 전송 실패: {response.text}")
    except Exception as e:
        print(f"🚫 텔레그램 요청 중 오류 발생: {e}")

# 텔레그램 메시지 템플릿 모음
MSG_AUTO_TRADE_START = (
    "🚀 <b>[자동매매 시작]</b>\n"
    "📍코인: <b>{market}</b>\n"
    "🔢 차수: <b>{max_levels}차</b>\n"
    "💵 시작가: {start_price:,}원\n"
    "💰 매수금액: {krw_amount:,}원"
)

MSG_BUY_ORDER = (
    "🛒 <b>{market}</b> | <b>{level}차 매수 주문 등록</b>\n"
    "📉 매수가: {buy_price:,}원\n"
    "📦 수량: {volume:.8f}"
)

MSG_SELL_ORDER = (
    "📤 <b>{market}</b> | <b>{level}차 매도 주문 등록</b>\n"
    "📈 매도가: {sell_price:,}원\n"
    "📦 수량: {volume:.8f}"
)

MSG_BUY_FILLED = (
    "✅ <b>[매수 체결]</b>\n"
    "📍 종목: <b>{market}</b>\n"
    "🔢 차수: <b>{level}차</b>\n"
    "💰 체결가: {buy_price:,}원\n"
    "📦 체결수량: {volume:.8f}\n"
    "⏰ 체결시간: {filled_time}"
)

MSG_SELL_FILLED = (
    "☑️ <b>[매도 체결]</b>\n"
    "📍 종목: <b>{market}</b>\n"
    "🔢 차수: <b>{level}차</b>\n"
    "💰 체결가: {sell_price:,}원\n"
    "📦 체결수량: {volume:.8f}\n"
    "💵 실현수익: <b>{profit:,.0f}원</b>\n"
    "💼 누적수익: <b>{realized_profit:,.0f}원</b>\n"
    "⏰ 체결시간: {filled_time}"
)