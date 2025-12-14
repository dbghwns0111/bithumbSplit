@echo off
chcp 65001 > nul

echo [🛠️ 빌드 시작]
pyinstaller bithumbSplit.spec --noconfirm
echo [✅ 빌드 완료]
pause