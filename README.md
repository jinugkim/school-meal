# school-meal

NEIS(나이스) Open API에서 오늘의 학교 급식 메뉴와 열량을 조회해, 평일 오전 7시 30분(KST)에 가족의 카카오톡 **나와의 채팅**으로 보내는 GitHub 템플릿입니다. 학교와 계정은 코드 수정 없이 GitHub Actions Secrets로 설정합니다.

## 먼저 알아둘 점

- 카카오톡 메시지 API 사용은 카카오 앱 설정과 사용자 동의 항목의 승인이 필요할 수 있습니다. Kakao Developers에서 메시지 API와 `talk_message` 동의 항목의 현재 사용 가능 여부를 확인하세요.
- 이 프로젝트는 GitHub Secrets에서 읽은 refresh token을 로그에 출력하지 않습니다. 단, 카카오가 갱신 응답에서 새 refresh token을 발급한 경우 자동으로 GitHub Secret에 기록할 수 없으므로 로그 경고에 따라 Secret 값을 업데이트해야 합니다.
- GitHub Actions의 예약 실행은 혼잡도에 따라 지연될 수 있습니다. 예약 기준 시각은 07:30 KST입니다.

## 1. 템플릿 저장소 만들기

1. GitHub에서 이 저장소의 **Use this template → Create a new repository**를 선택합니다.
2. 저장소를 가능하면 **Private**로 만들고, **Settings → Actions → General → Workflow permissions**에서 기본 읽기 권한을 유지합니다.
3. **Actions** 탭에서 워크플로 실행이 허용되어 있는지 확인합니다.

## 2. NEIS API 키와 학교 코드 준비

1. [공공데이터포털](https://www.data.go.kr/)에서 `나이스 교육정보 개방 포털 급식식단정보`를 찾아 활용 신청 후 인증키를 발급합니다. 승인된 활용 신청의 **일반 인증키(인코딩)** 값을 준비합니다.
2. [나이스 교육정보 개방 포털](https://open.neis.go.kr/)의 학교정보 조회에서 학교를 검색해 시도교육청 코드(`ATPT_OFCDC_SC_CODE`)와 표준학교코드(`SD_SCHUL_CODE`)를 확인합니다. 값은 숫자로 보이더라도 문자열 그대로 사용합니다.

## 3. Kakao 앱과 REST API 키 준비

1. [Kakao Developers](https://developers.kakao.com/)에서 앱을 만들고 카카오 로그인을 활성화합니다.
2. 앱의 **플랫폼 키**에서 REST API 키와, Client Secret 기능이 켜져 있다면 Client Secret 코드를 준비합니다.
3. 카카오 로그인 Redirect URI에 `http://127.0.0.1:5000/oauth`를 등록합니다.
4. **카카오 로그인 → 동의항목**에서 `카카오톡 메시지 전송 (talk_message)`을 사용할 수 있게 설정합니다. 토큰 발급 도구는 이 동의항목을 요청하므로, 각 계정이 다시 로그인해 동의해야 합니다. 메시지 템플릿의 링크 도메인(`open.neis.go.kr`)도 앱의 제품 링크 관리에 등록하고, 테스트 사용자/앱 상태/검수 요구 사항을 확인합니다.

## 4. 가족별 refresh token 발급

각 카카오 계정 소유자가 본인 기기에서 직접 진행합니다. refresh token은 계정 비밀번호와 같은 민감 정보입니다.

Python 3.10 이상을 설치하고 저장소 폴더에서 아래 명령을 실행합니다.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS/Linux:

```bash
export KAKAO_REST_API_KEY='발급받은 REST API 키'
export KAKAO_CLIENT_SECRET='설정한 경우에만 입력'
python get_tokens.py
```

Windows PowerShell:

```powershell
$env:KAKAO_REST_API_KEY = '발급받은 REST API 키'
$env:KAKAO_CLIENT_SECRET = '설정한 경우에만 입력'
python get_tokens.py
```

브라우저에서 `http://127.0.0.1:5000`을 열고 계정별로 로그인 및 동의합니다. 결과 화면의 refresh token을 복사합니다. 가족 계정을 바꿀 때는 로그아웃하거나 시크릿 창을 사용해 올바른 계정으로 인증하세요. 작업이 끝나면 서버를 `Ctrl+C`로 종료합니다. 토큰을 파일이나 공개 채팅에 저장하지 마세요.

## 5. GitHub Actions Secrets 등록

저장소의 **Settings → Secrets and variables → Actions → New repository secret**에서 다음 이름으로 등록합니다.

| Secret 이름 | 값 |
| --- | --- |
| `NEIS_API_KEY` | NEIS 일반 인증키(인코딩) |
| `OFFICE_CODE` | 학교의 시도교육청 코드 |
| `SCHOOL_CODE` | 학교 표준학교코드 |
| `KAKAO_REST_API_KEY` | Kakao 앱 REST API 키 |
| `KAKAO_CLIENT_SECRET` | Client Secret이 켜져 있으면 필수. 꺼져 있으면 빈 값 또는 Secret 생략 가능 |
| `KAKAO_REFRESH_TOKENS` | 가족별 refresh token 목록(JSON 배열 권장) |

refresh token 목록은 다음처럼 JSON 배열로 입력합니다. 따옴표는 JSON 문법에 맞게 포함합니다.

```json
["첫번째_계정_refresh_token", "두번째_계정_refresh_token"]
```

한 계정만 등록할 때도 배열 형식을 사용할 수 있습니다. 코드의 기본 설정은 모든 토큰을 같은 학교 급식 메시지 수신 대상으로 취급합니다.

## 6. 실행 확인과 운영

**Actions → Daily school meal → Run workflow**로 수동 실행하고 로그를 확인합니다. 실행 로그에는 토큰을 출력하지 않습니다. 예약 실행은 UTC 기준 `22:30`, 한국 시간 기준 월~금 `07:30`입니다.

- 급식 데이터가 없는 날에는 주말·공휴일·방학일 수 있다는 안내를 보냅니다.
- NEIS 요청이 실패하면 급식 조회 실패 안내를 카카오톡으로 보내고 수신자 전송을 계속 시도합니다.
- 한 카카오 계정이 만료/실패해도 다른 계정 전송은 계속됩니다. 모든 수신자 전송이 실패하면 워크플로가 실패로 표시됩니다.
- `refresh token rotated` 로그가 보이면 새 토큰이 발급된 해당 계정의 토큰을 `KAKAO_REFRESH_TOKENS` Secret에 반영하세요. 오래된 토큰은 만료될 수 있습니다.
- Kakao REST API 키의 Client Secret 설정을 변경했다면 GitHub Secret도 함께 수정해야 합니다.

## 로컬에서 급식 메시지 실행

필요한 환경 변수를 설정한 뒤 `python main.py`를 실행할 수 있습니다. 필수 값은 위 GitHub Secrets와 동일합니다. `KAKAO_REFRESH_TOKENS`는 JSON 배열 또는 쉼표로 구분한 값으로 읽습니다.

카카오 연동 전에 NEIS 조회만 확인하려면 `NEIS_API_KEY`, `OFFICE_CODE`, `SCHOOL_CODE`를 설정한 뒤 `python main.py --check-neis`를 실행합니다. 이 모드는 급식 메뉴와 열량을 출력하고 카카오 설정은 확인하지 않습니다. 일반 실행에서는 NEIS 조회 결과를 먼저 로그에 표시한 뒤 Kakao 환경 변수를 확인합니다.

## 보안

API 키와 토큰을 소스 코드, 커밋, 이슈, 공개 로그에 넣지 마세요. 유출이 의심되면 해당 카카오 앱/토큰을 폐기 또는 재발급하고 GitHub Secret을 갱신하세요. 토큰 발급 도구는 `127.0.0.1`에서만 실행합니다.

## 라이선스

필요에 따라 저장소에 오픈소스 라이선스를 추가해 배포하세요.
