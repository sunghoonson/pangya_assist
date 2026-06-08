팡야 어시스트 + Acrisio 계산기 탭 통합본

실행 방법:
1. 기존 프로젝트 폴더에 pangya_acrisio.py 파일을 복사합니다.
2. pangya_overlay_gui_with_calculator.py를 실행하거나, 기존 pangya_overlay_gui.py를 이 파일로 교체합니다.
3. 필요한 패키지는 requirements.txt 기준으로 설치합니다.

명령 예:
python -m pip install -r requirements.txt
python pangya_overlay_gui_with_calculator.py

구성:
- 첫 번째 탭: 기존 오버레이 설정
- 두 번째 탭: Acrisio smart_calculator.js 기반 계산기 입력/결과 GUI

주의:
- 계산 엔진은 smart_calculator.js를 Python으로 1차 포팅한 pangya_acrisio.py를 사용합니다.
- 원본 JS의 line_ball Math.random()은 기본 고정값 0으로 처리했고, GUI에서 랜덤 옵션을 켤 수 있습니다.


[v2 변경]
- 계산기 탭에 입력 저장 / 입력 불러오기 버튼을 추가했습니다.
- 계산기 입력값은 실행 파일 또는 py 파일과 같은 폴더의 pangya_calculator_settings.json에 저장됩니다.
- 오버레이 설정은 기존처럼 pangya_overlay_settings.json에 저장됩니다.


[v3 변경]
- 계산기 탭에 표시 단위 / 장판 보정 영역을 추가했습니다.
- YARDS_TO_PB, YARDS_TO_PBA, YARDS_TO_PBA+ 값을 GUI에서 조정할 수 있습니다.
- 기존 한국어 계산기의 장판값에 맞추기 위해 '장판 환산값(PB당)'과 '스마트 나눗값'을 추가했습니다.
- 기본 장판 환산값은 0.2121입니다. 예: 8.41pb * 0.2121 = 1.784칸.
- 이 값들은 물리 계산 자체가 아니라 결과 표시/환산값 보정용입니다.
