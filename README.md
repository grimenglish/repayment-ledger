# 우리집 상환장부 — 개인용 Streamlit

Streamlit Cloud에 올려 휴대폰·PC 브라우저에서 사용하는 앱입니다. 데이터는 본인의 Google Sheets에 저장합니다. 실제 상환 내역은 비어 있습니다.

## 기능
- 전체 2억, 엄마·본인 각 1억의 잔액과 반원 게이지
- 날짜·은행·실제 송금자, 총 송금액, 엄마·본인 원금 배분, 이자, 메모
- 월 목표(엄마 400만 / 본인 100만 기본), 빠른 입력, 예상 완납월
- 월별 조회, 수정·삭제, 잔액 추이, 엑셀 요약·내역·월별 합계
- 선상환 비교, 원금 초과·배분 불일치·미래 날짜 차단
- 로그인 전에는 데이터 조회도 실행하지 않음

## 1. 코드 업로드
본인 GitHub에 비공개 저장소를 만들고 이 폴더 안의 파일을 올립니다. 실행 파일은 `app.py`입니다. `.streamlit/config.toml`도 포함하세요.
실제 Secrets, 서비스 계정 JSON은 GitHub에 올리지 마세요.

## 2. Google Sheets 저장 연결
1. 본인 Drive에서 빈 스프레드시트를 만듭니다. 공개 공유를 끕니다.
2. URL의 `/d/`와 `/edit` 사이 ID를 복사합니다.
3. https://console.cloud.google.com/ 에서 프로젝트 생성 후 Google Sheets API를 사용 설정합니다.
4. IAM 및 관리자 → 서비스 계정 → 계정 생성 → 키 → JSON 키를 생성합니다.
5. JSON의 `client_email` 주소에 위 스프레드시트를 편집자로 공유합니다.
6. `secrets.example.toml`의 `spreadsheet_id`와 `[gcp_service_account]` 값을 채웁니다.

`ledger_events_v1` 탭은 자동 생성됩니다. 다른 탭은 변경하지 않습니다. 수정·삭제도 이벤트로 남기며 Excel에는 현재 유효한 내역만 표시합니다. 이벤트 탭을 직접 수정하거나 정렬하지 마세요.
동일 앱의 여러 화면 사이 변경 충돌을 감지합니다. 여러 별도 앱 배포에서 같은 시트를 동시에 수정하는 방식은 지원하지 않습니다.

## 3. 나만 로그인하기
권장 방식은 본인 Google 계정만 허용하는 로그인입니다.
1. Google Cloud → Google Auth Platform에서 OAuth 동의 화면을 설정합니다. 테스트 상태라면 본인 계정을 테스트 사용자로 추가합니다.
2. OAuth 클라이언트 ID → 웹 애플리케이션을 생성합니다.
3. 승인된 리디렉션 URI에 `https://본인앱.streamlit.app/oauth2callback`을 등록합니다.
4. Secrets에서 `login_mode = "google"`, `allowed_email = "본인@gmail.com"`으로 지정합니다.
5. 예시 파일의 `[auth]`, `[auth.google]` 주석을 풀고 OAuth ID/Secret, 긴 임의의 `cookie_secret`을 넣습니다.
6. Google에서 검증한 본인 이메일만 장부를 열 수 있습니다.

간단한 비밀번호 로그인도 됩니다. `login_mode = "password"`로 두고 `python make_password.py`로 생성한 `[login]` 값을 사용하세요. 해시를 저장하며 로그인은 8시간 유지됩니다. 실패 지연은 브라우저 세션 단위입니다. 본인 계정 확인은 Google 로그인이 더 적합합니다.
Streamlit Cloud 공유 설정에서도 앱을 비공개로 두고 본인만 허용하세요. 해당 옵션의 제공 조건은 계정에서 확인하세요.

## 4. Streamlit Cloud 배포
1. https://share.streamlit.io/ 에서 본인 GitHub 계정으로 로그인합니다.
2. Create app → 위 저장소 → Main file path `app.py`를 지정합니다. 하위 폴더에 올렸다면 실제 경로를 사용합니다.
3. Python 3.11 이상을 선택합니다.
4. Advanced settings → Secrets에 값이 채워진 TOML 전체를 붙여넣습니다.
5. Deploy를 누릅니다. 앱 주소 확정 후 Google OAuth와 Secrets의 redirect_uri를 동일하게 맞춥니다.
6. 휴대폰·PC에서 같은 앱 주소로 사용합니다. 브라우저를 닫아도 Google Sheets에 내역이 남습니다.

이 파일은 코드 묶음입니다. 본인 계정 연결 및 배포는 위 설정이 한 번 필요합니다.

## 계산 기준
각 1억에서 원금 상환액만 차감합니다. 이자는 별도 기록합니다.
완납월은 이번 달 남은 목표를 이번 달에 갚고 다음 달부터 매월 목표액을 갚는 가정입니다. 월 목표가 0인데 잔액이 있으면 계산하지 않습니다.
선상환은 이번 달 즉시 추가 상환하고 이번 달 목표에도 포함하는 가정입니다. 계산만 하며 내역에 저장하지 않습니다. 실제 납부일·이자율·연체료는 자동 계산하지 않습니다.

## 파일
app.py: 화면·로그인 / core.py: 계산·엑셀 / storage.py: Google 저장 / requirements.txt: 의존성 / secrets.example.toml: 연결 예시 / make_password.py: 비밀번호 설정 / tests.py: 검증

개발 확인: `pip install -r requirements.txt` 후 `python -m unittest tests -v`.
필요한 경우만 `.streamlit/secrets.toml`을 만들고 `streamlit run app.py`로 로컬 확인할 수 있습니다. 실제 사용은 Cloud 기준입니다.

## 공식 자료
- 배포: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- Secrets: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- Google 로그인: https://docs.streamlit.io/develop/concepts/connections/authentication
- 서비스 계정: https://docs.gspread.org/en/master/oauth2.html

## 안정성 점검 (v1.4)
자체 테스트 23개 통과. 완납월 계산은 무작위 조건 1,000건을 월별 반복 계산 결과와 비교했습니다.
본인 Google 이메일 및 이메일 검증 여부에 따른 접근 차단, 저장·수정·삭제, 원금 초과 차단, 동시 저장 충돌, 저장 성공 후 응답 유실, 손상된 내역·월 목표·JSON, 키 줄바꿈 보정, 빈 시트 초기화, 엑셀 수식 입력 차단과 완납 화면을 점검했습니다.
잘못된 저장 내역은 화면 계산 전에 차단합니다. 메모의 엑셀 처리 불가 문자도 입력 시 차단합니다. Google 요청에는 연결 10초·읽기 30초 제한을 설정했습니다.
검증 범위는 계산·엑셀·모의 Google 저장소·Streamlit 테스트 화면입니다. 실제 사용자 Google 계정 연결 및 Cloud에서의 동작은 이 자체 테스트에 포함되지 않습니다.
