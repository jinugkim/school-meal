# school-meal

NEIS(나이스) Open API에서 급식 메뉴와 열량을 조회해, 급식 전날 오후 9시와 당일 평일 오전 6시 25분(KST)에 가족의 카카오톡 **나와의 채팅**으로 보내는 GitHub 템플릿입니다. 주말 오전 9시(KST)에는 55주 분량의 영어 시편 구절을 설정된 가족 계정 모두에게 보냅니다. 학교와 계정은 코드 수정 없이 GitHub Actions Secrets로 설정합니다.

## 먼저 알아둘 점

- 카카오톡 메시지 API 사용은 카카오 앱 설정과 사용자 동의 항목의 승인이 필요할 수 있습니다. Kakao Developers에서 메시지 API와 `talk_message` 동의 항목의 현재 사용 가능 여부를 확인하세요.
- 이 프로젝트는 GitHub Secrets에서 읽은 refresh token을 로그에 출력하지 않습니다. 단, 카카오가 갱신 응답에서 새 refresh token을 발급한 경우 자동으로 GitHub Secret에 기록할 수 없으므로 로그 경고에 따라 Secret 값을 업데이트해야 합니다.
- GitHub Actions의 예약 실행은 혼잡도에 따라 지연될 수 있습니다. 예약 기준 시각은 전날 21:00, 평일 당일 06:25, 주말 시편 09:00 KST입니다.

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
| `KAKAO_REFRESH_TOKEN_ME` | 본인 카카오 계정의 refresh token |
| `KAKAO_REFRESH_TOKEN_WIFE` | 배우자 카카오 계정의 refresh token |
| `KAKAO_REFRESH_TOKEN_DAUGHTER` | 딸 카카오 계정의 refresh token |

각 Secret에는 해당 카카오 계정에서 발급한 refresh token 하나만 입력합니다. Secret이 설정된 계정마다 해당 계정의 ‘나와의 채팅’으로 급식 메뉴와 주말 시편 메시지가 따로 전송됩니다. 기술 안내(토큰 교체, NEIS/카카오 전송 실패)는 본인 계정에만 전송합니다. 계정별 발급 방법은 `get_tokens.py` 절차를 사용하고, 발급한 토큰은 로그인한 계정에 맞는 Secret에 넣습니다. 예전 `KAKAO_REFRESH_TOKENS` 배열은 개별 Secret을 하나도 설정하지 않은 경우에만 호환용으로 사용됩니다. 전환할 때는 가족별 Secret을 모두 입력하면 배열은 무시되어 중복 발송되지 않습니다.

## Refresh token 갱신

갱신 대상은 인증서가 아니라 카카오 **refresh token**입니다. 기본 유효기간은 2개월이며, 만료 1개월 전부터 갱신할 수 있습니다. 카카오가 새 토큰을 반환하면 기존 토큰은 폐기됩니다. [카카오 토큰 안내](https://developers.kakao.com/docs/ko/kakaologin/common)

알림 메시지를 받으면 다음 순서로 갱신합니다.

1. 저장소에서 가상환경을 활성화하고, 최초 발급 때와 같은 앱의 REST API 키를 설정합니다.

   ```bash
   source .venv/bin/activate
   export KAKAO_REST_API_KEY='같은 앱의 REST API 키'
   export KAKAO_CLIENT_SECRET='Client Secret이 켜져 있으면 현재 값'
   python get_tokens.py
   ```

   Client Secret이 꺼져 있다면 `export KAKAO_CLIENT_SECRET=...` 대신 `unset KAKAO_CLIENT_SECRET`을 실행합니다.
2. `http://127.0.0.1:5000`에서 해당 카카오 계정으로 로그인하고 동의한 뒤 새 refresh token을 복사합니다.
3. GitHub **Settings → Secrets and variables → Actions**에서 갱신 안내에 표시된 해당 계정 Secret(예: `KAKAO_REFRESH_TOKEN_WIFE`)만 새 토큰으로 교체합니다. 토큰은 채팅이나 코드에 붙여넣지 않습니다.
4. Actions에서 워크플로를 수동 실행해 전송을 확인하고, 로컬 서버는 `Ctrl+C`로 종료합니다.

갱신 때 자주 발생하는 설정 오류:

| 오류 | 확인할 설정 |
| --- | --- |
| `KOE004` | Kakao Developers에서 **카카오 로그인 사용 설정**이 ON인지 확인 |
| `KOE006` | Redirect URI가 `http://127.0.0.1:5000/oauth`와 정확히 일치하는지 확인 |
| 403 `insufficient scopes` | `카카오 로그인 → 동의항목`에서 `talk_message`를 사용할 수 있게 하고, 재로그인 때 메시지 전송 동의 |
| `invalid_client` | 토큰 발급에 사용한 앱의 REST API 키와 Client Secret이 GitHub 및 로컬 설정과 같은지 확인 |
| `expired_or_invalid_refresh_token` | 만료·폐기된 토큰이므로 위 절차로 새 토큰 발급 |

## 6. 실행 확인과 운영

**Actions → Daily school meal → Run workflow**로 수동 실행하고 로그를 확인합니다. 주말에 수동 실행하면 월요일 급식을 조회합니다. 평일 수동 실행은 당일 급식을 조회합니다. 급식 정보가 없는 수동 실행은 본인에게만 테스트/상태 안내를 보냅니다. 실행 로그에는 KST 실행 시각과 조회 대상일이 표시되며, 토큰 값은 출력하지 않습니다. 예약 실행은 매일 전날 급식을 확인하는 UTC `12:00`(KST `21:00`), 당일 급식을 확인하는 UTC `21:25`(KST 평일 `06:25`), 주말 시편을 보내는 UTC `00:00`(KST 토·일 `09:00`)입니다. 예약 급식 실행에서 해당 날짜의 NEIS 급식 정보가 없으면 카카오 메시지를 보내지 않습니다.

- 예약 실행에서 해당 날짜의 급식 데이터가 없으면 메시지를 보내지 않습니다. 수동 실행에서 데이터가 없으면 시스템 상태 안내를 본인에게만 보냅니다.
- 급식 대상일이 토요일·일요일 또는 한국 공휴일이면 NEIS 급식 조회와 급식 메시지 발송을 건너뛰고, 요약에 사유를 표시합니다. 평일 중식은 메뉴가 등록된 경우 발송합니다. 석식은 공휴일이 아닌 화요일과 목요일에만 별도 메시지로 발송합니다. 카카오 텍스트 템플릿의 200자 제한을 넘으면 메뉴 끝을 줄여 전송합니다.
- NEIS 요청이 실패하면 배우자와 딸에게 시스템 오류 메시지를 보내지 않습니다. 본인 계정으로만 안내하며, GitHub Actions 실행도 실패로 표시합니다.
- 한 카카오 계정이 만료/실패해도 다른 계정 전송은 계속됩니다. 일부 수신자만 실패해도 실행을 실패로 표시하고, 원인 안내는 본인 계정으로만 보냅니다. 본인 계정 전송 자체가 실패하면 안내 메시지를 받을 수 없으므로 Actions 로그를 확인합니다.
- refresh token이 교체되면 본인 계정으로 해당 가족 Secret의 갱신 안내를 보냅니다. 배우자와 딸에게는 기술 안내를 보내지 않습니다. 새 토큰 값은 알림에 포함하지 않습니다. 메시지에 표시된 해당 계정 Secret만 교체하세요.
- 토요일과 일요일 오전 9시에는 [55주 시편 목록](weekend_psalms.md)을 순서대로 순환해 설정된 가족 계정마다 하루 한 구절씩 보냅니다. 첫 주는 2026년 10월 17일에 시작하며, 매주 같은 항목의 토요일·일요일 구절을 보냅니다. WEB Updated는 퍼블릭 도메인 번역이며, 카카오 메시지에는 구절과 장절이 들어갑니다.
- 시편 목록은 정확히 55주 순서인지, 각 주에 토·일 구절이 있고 형식이 맞는지, 메시지가 200자 이내인지 검사합니다. 로컬에서는 `python main.py --validate-weekend-psalms`로 확인할 수 있으며, 목록이나 검증 코드가 바뀌면 GitHub Actions에서도 자동 검증합니다.
- Kakao REST API 키의 Client Secret 설정을 변경했다면 GitHub Secret도 함께 수정해야 합니다.

## 로컬에서 급식 메시지 실행

필요한 환경 변수를 설정한 뒤 `python main.py`를 실행할 수 있습니다. Kakao refresh token은 위 가족별 Secret과 같은 환경 변수 이름을 사용합니다. 기존 배열 설정은 개별 Secret이 하나도 없을 때만 호환용으로 읽습니다.

카카오 연동 전에 NEIS 조회만 확인하려면 `NEIS_API_KEY`, `OFFICE_CODE`, `SCHOOL_CODE`를 설정한 뒤 `python main.py --check-neis`를 실행합니다. 이 모드는 급식 메뉴와 열량을 출력하고 카카오 설정은 확인하지 않습니다. 일반 실행에서는 NEIS 조회 결과를 먼저 로그에 표시한 뒤 Kakao 환경 변수를 확인합니다.

시편 목록을 수정한 뒤에는 `python main.py --validate-weekend-psalms`를 실행해 주차 순서, 형식, 메시지 길이를 확인합니다. 같은 검증은 GitHub Actions에서 목록 변경 시 자동으로 실행됩니다.

## 보안

API 키와 토큰을 소스 코드, 커밋, 이슈, 공개 로그에 넣지 마세요. 유출이 의심되면 해당 카카오 앱/토큰을 폐기 또는 재발급하고 GitHub Secret을 갱신하세요. 토큰 발급 도구는 `127.0.0.1`에서만 실행합니다.

## 라이선스

필요에 따라 저장소에 오픈소스 라이선스를 추가해 배포하세요.
