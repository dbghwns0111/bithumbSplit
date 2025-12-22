# 🚀 bithumbSplit 자동매매 시작 가이드

## 📋 전체 프로세스 요약

```
1️⃣ Git에서 코드 가져오기
   ↓
2️⃣ exe 파일 빌드 (처음 1회만)
   ↓
3️⃣ GUI로 설정 입력
   ↓
4️⃣ Watchdog 실행 (24/7 감시)
   ↓
5️⃣ 자동 거래 시작
```

---

## 📥 **Step 1: 서버에서 코드 가져오기**

### 명령어 (PowerShell 또는 CMD)
```powershell
cd C:\Users\USER\VS_CODE\BithumbSplit

# 최신 코드 가져오기
git fetch origin
git pull origin main
```

✅ **확인**: 새로운 파일들이 프로젝트에 추가됨
- `watchdog.py` (새 파일)
- `worker.py` (새 파일)
- `start_watchdog.bat` (새 파일)
- `gui/gui_app.py` (수정됨)

---

## 🔨 **Step 2: exe 파일 빌드 (첫 실행 시 1회만)**

### 방법 1: 배치 파일 실행 (권장)
```bash
C:\Users\USER\VS_CODE\BithumbSplit\build_bithumbSplit.bat
```

- 배치 파일이 자동으로 필요한 작업 수행
- 1~3분 정도 소요
- **dist/bithumbSplit.exe** 파일 생성 확인

### 방법 2: 수동으로 빌드
```powershell
cd C:\Users\USER\VS_CODE\BithumbSplit

# requirements 설치
pip install -r requirements.txt

# PyInstaller로 빌드
pyinstaller bithumbSplit.spec
```

✅ **확인**: `dist/` 폴더에 `bithumbSplit.exe` 파일 생성됨

**⚠️ 주의**: 
- 코드를 수정하지 않으면 다시 빌드할 필요 없음
- 코드 수정 후에만 다시 실행

---

## ⚙️ **Step 3: GUI에서 설정 입력**

### 명령어
```powershell
cd C:\Users\USER\VS_CODE\BithumbSplit
python main.py
```

### 설정 방법

GUI가 열리면 각 마켓(BTC, USDT, XRP)별로 다음을 입력:

#### **🔹 BTC**
| 항목 | 값 | 설명 |
|------|-----|------|
| 시작가 | 94000000 | 첫 매수 가격 (원) |
| 매수금액 | 1000000 | 각 차수당 매수금액 (원) |
| 최대차수 | 60 | 최대 거래 차수 |
| 매수/매도 간격 | 0.2 / 0.3 | 간격 (%) |

#### **🔹 USDT**
| 항목 | 값 | 설명 |
|------|-----|------|
| 시작가 | 1200 | 첫 매수 가격 (원) |
| 매수금액 | 1000000 | 각 차수당 매수금액 (원) |
| 최대차수 | 40 | 최대 거래 차수 |
| 매수/매도 간격 | 0.2 / 0.3 | 간격 (%) |

#### **🔹 XRP**
| 항목 | 값 | 설명 |
|------|-----|------|
| 시작가 | 2300 | 첫 매수 가격 (원) |
| 매수금액 | 500000 | 각 차수당 매수금액 (원) |
| 최대차수 | 50 | 최대 거래 차수 |
| 매수/매도 간격 | 0.2 / 0.3 | 간격 (%) |

### 버튼 클릭
**"🚀 설정 저장 & 자동매매 시작"** 클릭

✅ **결과**: 
- `config/markets_config.json` 파일 생성
- 다음 메시지 표시: "watchdog.bat을 실행하여 자동매매를 시작하세요"

---

## 🐕 **Step 4: Watchdog 실행 (24/7 감시)**

### 방법 1: 배치 파일 (권장)
```bash
C:\Users\USER\VS_CODE\BithumbSplit\start_watchdog.bat
```

콘솔 창이 열리고 다음과 같이 표시됨:
```
🚀 Watchdog 시작...

✅ markets_config.json 로드 완료: ['BTC', 'USDT', 'XRP']

📍 모니터링 마켓: BTC, USDT, XRP
⏱️ 타임아웃: 120초
📊 체크 주기: 30초
📈 정기 리포트: 1시간마다

🔄 [BTC] 프로세스 재시작 중...
✅ [BTC] 프로세스 재시작 완료 (PID: 12345)

🔄 [USDT] 프로세스 재시작 중...
✅ [USDT] 프로세스 재시작 완료 (PID: 12346)

🔄 [XRP] 프로세스 재시작 중...
✅ [XRP] 프로세스 재시작 완료 (PID: 12347)
```

### 방법 2: 수동으로 실행
```powershell
cd C:\Users\USER\VS_CODE\BithumbSplit
python watchdog.py
```

✅ **Watchdog이 자동으로:**
1. 3개 마켓(BTC, USDT, XRP) 모두 시작
2. 각각 독립적으로 자동매매 진행
3. 30초마다 상태 확인
4. 문제 시 자동 재시작
5. 1시간마다 Telegram 리포트 전송

---

## ✅ **자동매매 시작 확인**

### 1️⃣ 프로세스 확인
```powershell
# 실행 중인 Python 프로세스 확인
Get-Process python | Where-Object {$_.Name -like "python*"}
```

→ python.exe 여러 개가 실행 중이면 정상

### 2️⃣ Heartbeat 파일 확인
```powershell
ls -la C:\Users\USER\VS_CODE\BithumbSplit\logs\
```

→ 다음 파일들이 30초마다 업데이트됨:
- `heartbeat_KRW_BTC.json`
- `heartbeat_KRW_USDT.json`
- `heartbeat_KRW_XRP.json`

### 3️⃣ Telegram 알림 확인
- 1시간마다 정기 리포트 수신
- 문제 발생 시 즉시 알림

---

## 🛑 **자동매매 중단**

### GUI에서 중단
```
"🛑 자동매매 중단" 버튼 클릭
→ 확인 메시지 출력
→ "start_watchdog.bat" 창을 닫으세요
```

### 콘솔에서 중단
```
Watchdog 콘솔 창 닫기 (Ctrl+C 또는 X 버튼)
```

---

## 📊 **모니터링**

### 상태 확인
```powershell
python watchdog.py --status
```

출력 예:
```
🔍 Watchdog 상태 확인 - 2025-12-22 22:30:45
============================================================

📊 BTC:
   타임스탐프: 2025-12-22T22:30:45.123456
   상태: running
   누적수익: 125000원
   현재 차수: 15차
   미체결 주문: 2개

📊 USDT:
   타임스탐프: 2025-12-22T22:30:44.987654
   상태: running
   누적수익: 45000원
   현재 차수: 8차
   미체결 주문: 1개

📊 XRP:
   타임스탐프: 2025-12-22T22:30:43.456789
   상태: running
   누적수익: -12000원
   현재 차수: 12차
   미체결 주문: 3개
```

---

## 📅 **정기 리포트 (Telegram)**

매 1시간마다 자동으로 다음 정보 수신:

```
📊 [Watchdog 정기 리포트]
⏱️ 운영 시간: 2시간 15분

✅ BTC:
   현재 차수: 15차
   누적 수익: 125000원
   미체결 주문: 2개
   📋 주문 목록:
      🛒 매수 94000000원 x 0.00100000 (15:30:45)
      📤 매도 94281000원 x 0.00100000 (15:25:30)
      ... 외 3개

✅ USDT:
   현재 차수: 8차
   누적 수익: 45000원
   미체결 주문: 1개
   📋 주문 목록:
      🛒 매수 1200원 x 833.33 (14:45:22)
      ... 외 2개

✅ XRP:
   현재 차수: 12차
   누적 수익: -12000원
   미체결 주문: 3개
   📋 주문 목록:
      📤 매도 2350원 x 100.00 (13:15:10)
      ... 외 1개

💰 총 누적 수익: 158000원
📍 활성 마켓: 3/3개

✨ 모든 마켓 정상 운영 중
```

---

## ⚠️ **문제 해결**

### Q1: Watchdog 시작 후 "markets_config.json을 찾을 수 없습니다" 에러
**A**: Step 3에서 GUI의 "설정 저장 & 자동매매 시작" 버튼을 클릭하지 않았습니다.
```
1. python main.py 실행
2. 설정 입력
3. "설정 저장 & 자동매매 시작" 클릭
4. 그 후 start_watchdog.bat 실행
```

### Q2: Worker 프로세스가 계속 재시작됨
**A**: 설정값 오류 가능성
- 시작가가 현재 시장가와 너무 차이 나지 않는지 확인
- 매수금액이 너무 작지 않은지 확인 (최소 1000원 이상)

### Q3: Telegram 알림이 안 옴
**A**: API 키 설정 확인
```
1. utils/telegram.py에서 BOT_TOKEN, CHAT_ID 확인
2. Telegram 봇 토큰이 유효한지 확인
```

### Q4: exe 파일 생성 실패
**A**: PyInstaller 재설치
```powershell
pip install --upgrade pyinstaller
python build_bithumbSplit.bat
```

---

## 🔄 **코드 업데이트 후**

코드를 깃에서 다시 가져온 후:

```powershell
# 1️⃣ 코드 가져오기
git fetch origin
git pull origin main

# 2️⃣ exe 파일 다시 빌드
build_bithumbSplit.bat

# 3️⃣ Watchdog 재시작
start_watchdog.bat
```

---

## 📝 **요약: 빠른 참고**

| 상황 | 명령어 |
|------|--------|
| 첫 셋업 | `build_bithumbSplit.bat` → `python main.py` → `start_watchdog.bat` |
| 매일 시작 | `start_watchdog.bat` |
| 상태 확인 | `python watchdog.py --status` |
| 자동매매 중단 | Watchdog 창 닫기 또는 `Ctrl+C` |
| 코드 업데이트 | `git pull origin main` → `build_bithumbSplit.bat` → `start_watchdog.bat` |

---

## 🎯 **완전 자동화 (Windows Task Scheduler)**

매일 자동으로 Watchdog을 시작하려면:

### 1️⃣ Task Scheduler 열기
```
Windows 시작 → "작업 스케줄러" 검색 → 열기
```

### 2️⃣ "기본 작업 만들기"
- **이름**: `BithumbSplit Watchdog`
- **설명**: 자동매매 감시

### 3️⃣ 트리거 설정
- **시작**: 컴퓨터 시작 시
- **반복**: 매일

### 4️⃣ 작업 설정
- **프로그램**: `C:\Users\USER\VS_CODE\BithumbSplit\start_watchdog.bat`
- **시작 위치**: `C:\Users\USER\VS_CODE\BithumbSplit`

### 5️⃣ "마침" 클릭 → 자동으로 실행됨

---

**✅ 모든 준비가 완료되었습니다!**

질문이 있으면 언제든 물어보세요.
