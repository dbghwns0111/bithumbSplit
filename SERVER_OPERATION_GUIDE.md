# 서버 24/7 운영 가이드

## 개요
GUI는 **모니터링/명령용**으로만 사용하고, 실제 자동매매는 **워커 프로세스(worker.py)**로 실행하며, **Watchdog(watchdog.py)**이 자동으로 감시 및 재시작합니다.

---

## 📋 구성

### 1. worker.py - CLI 기반 자동매매 워커
GUI 없이 순수 자동매매만 실행. 30초마다 하트비트 파일을 작성하여 살아있음을 신호합니다.

**실행:**
```bash
python worker.py --market BTC --start-price 100000000 --krw-amount 1000000 --max-levels 60 --buy-gap 0.2 --sell-gap 0.3
```

**옵션:**
- `--market` : 코인 코드 (BTC, USDT, XRP 등, 기본값: BTC)
- `--start-price` : 시작 매수 가격
- `--krw-amount` : 차수별 매수 금액
- `--max-levels` : 최대 차수
- `--buy-gap` : 매수 간격 (%, 기본값: 0.2)
- `--sell-gap` : 매도 간격 (%, 기본값: 0.3)
- `--resume-level` : 재시작 차수 (0=새시작, N=N차부터, 기본값: 0)

---

### 2. watchdog.py - 프로세스 감시 및 자동 재시작
- **30초 주기**로 하트비트 파일 확인
- **2분(120초)** 이상 응답 없으면 프로세스 자동 재시작
- 여러 마켓 동시 모니터링

**실행:**
```bash
# 감시 시작
python watchdog.py

# 현재 상태만 확인
python watchdog.py --status
```

---

## 🚀 운영 방식

### 권장 구성 (Windows)

#### 1단계: 설정 파일 작성 (선택)
각 마켓별로 `config/strategy_BTC.json` 같은 파일을 만들어 기본 설정 저장:

```json
{
  "start_price": 100000000,
  "krw_amount": 1000000,
  "max_levels": 60,
  "buy_gap": 0.2,
  "buy_mode": "percent",
  "sell_gap": 0.3,
  "sell_mode": "percent"
}
```

#### 2단계: Watchdog 시작 (배치 스크립트)
`start_watchdog.bat` 생성:

```batch
@echo off
cd /d C:\Users\USER\VS_CODE\BithumbSplit
python watchdog.py
pause
```

작업 스케줄러에 등록:
1. 제어판 → 관리 도구 → 작업 스케줄러
2. 작업 생성
   - 트리거: `시스템 시작 시` 또는 `로그온 시`
   - 작업: `C:\Users\USER\VS_CODE\BithumbSplit\start_watchdog.bat` 실행
   - 옵션: **"작업이 실패해도 계속 실행"** 체크

#### 3단계: GUI는 선택적으로
GUI가 필요할 때만 수동으로 실행:
- 상태 모니터링
- 긴급 중단 (모든 주문 취소)
- 재시작 차수 수정

---

## 📊 모니터링

### 헬스비트 파일 확인
```bash
python watchdog.py --status
```

결과 예시:
```
============================================================
🔍 Watchdog 상태 확인 - 2025-12-22 18:15:30
============================================================

📊 BTC:
   타임스탐프: 2025-12-22T18:15:28.123456
   상태: running
   누적수익: 150,000원
   현재 차수: 28차
   미체결 주문: 2개

📊 USDT:
   타임스탐프: 2025-12-22T18:15:29.654321
   상태: running
   누적수익: 85,000원
   현재 차수: 15차
   미체결 주문: 2개
```

### 로그 확인
```bash
# 상태 파일
logs/autotrade_state_KRW_BTC.json

# 하트비트 파일
logs/heartbeat_KRW_BTC.json
```

---

## 🔧 문제 해결

### 프로세스가 자동으로 재시작되는 경우
1. **네트워크 일시 오류** (자동 복구)
2. **GUI 프리즈** (Watchdog이 자동으로 재시작)
3. **API 타임아웃** (자동 복구 로직 실행)

→ **모두 정상이며, 자동매매는 중단되지 않습니다.**

### 로그를 확인하고 싶으면
```bash
# 최근 상태 출력
type logs\autotrade_state_KRW_BTC.json

# 최근 하트비트 출력
type logs\heartbeat_KRW_BTC.json
```

---

## 📈 권장 설정

| 항목 | 권장값 | 이유 |
|------|-------|------|
| 타임아웃 | 120초 | 네트워크 지연 대비 |
| 체크 주기 | 30초 | 빠른 재시작 감지 |
| 헬스체크 주기 | 60초 | 자동 복구 용이 |
| sleep_sec | 5초 | 루프 응답성 |

---

## ⚠️ 주의사항

1. **GUI 실행 중 worker 실행 금지**
   - 같은 마켓에서 중복 주문 발생 가능
   
2. **Watchdog 중단 금지**
   - 프로세스가 죽으면 자동 재시작 불가

3. **설정 변경 시**
   - 재시작 차수를 명시적으로 설정
   - 기존 주문 상태 확인 후 진행

4. **디스크 공간 확인**
   - 로그 파일이 주기적으로 삭제되지 않으면 증가
   - 월 1회 정도 `logs/` 폴더 정리 권장

---

## 🔐 안정성 향상 팁

### 1. 매일 자정 재시작 (선택)
작업 스케줄러:
- 트리거: 매일 00:00
- 작업: Watchdog 프로세스 종료 → 1분 대기 → 재시작

### 2. 원격 모니터링 (텔레그램)
- Watchdog은 오류 시 텔레그램 알림 전송
- 주문 체결 시 즉시 알림 수신

### 3. 리소스 모니터링
Windows 작업 관리자에서 python.exe 메모리 확인:
- 정상: 100~300MB
- 누수: 500MB 이상 → Watchdog이 자동 재시작

---

## 📞 긴급 처리

**모든 주문 긴급 취소:**
```bash
# GUI 실행 후 "전략 중단" 버튼 클릭
# 또는
python -c "from api.api import cancel_all_orders; cancel_all_orders('KRW-BTC')"
```

**로그 초기화:**
```bash
del logs\*.json
```

---

이 구성으로 **서버 리소스가 제한적**이어도 **24/7 자동매매**가 안정적으로 운영됩니다! 🎉
