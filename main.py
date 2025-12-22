# bithumbSplit/main.py
# GUI 실행 엔트리 포인트

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
base_path = Path(__file__).parent
if str(base_path) not in sys.path:
    sys.path.insert(0, str(base_path))

# GUI 앱 실행
if __name__ == '__main__':
    from gui import gui_app
    gui_app.app.mainloop()