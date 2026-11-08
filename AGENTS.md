# school-meal AI Context & System State

> 이 파일은 AI 코딩 어시스턴트가 `school-meal` 프로젝트의 현 상태, 아키텍처, 스케줄링 방식, 카카오톡 인증 구조를 즉시 파악하도록 돕는 컨텍스트 문서입니다.

---

## 1. 프로젝트 개요 & 목적
- **목적**: 
  - **평일 (월~금)**: NEIS(나이스) Open API에서 대원국제중학교 급식 메뉴 및 열량을 조회하여 가족(본인, 배우자, 딸)에게 카카오톡 메시지로 자동 발송.
  - **주말 (토~일)**: 55주 시편 말씀(`weekend_psalms.md`)을 순서대로 발송하고, 발송 기록(`data/weekend_psalm_history.json`)을 커밋하여 GitHub Pages로 자동 배포.
- **실행 시간**: **매일 아침 06:30 정각 (한국 표준시 KST)**

---

## 2. 아키텍처 변경 및 현재 스케줄링 구조 (★핵심)

```mermaid
flowchart TD
    subgraph 이전_구조["[이전 구조] GitHub Actions 내장 Cron (문제점)"]
        A1["GitHub Actions schedule cron"] -->|부하 시 15분~1시간 심한 지연| A2["메시지 늦게 도착"]
    end

    subgraph 현재_구조["[현재 구조] Google Cloud Scheduler 정시 트리거 (완전 해결)"]
        B1["Google Cloud Scheduler (30 6 * * *)"] -->|매일 06:30:00 칼같이 호출 (오차 0초)| B2["GitHub Actions workflow_dispatch API"]
        B2 --> B3{"KST 요일 판별 (date +%u)"}
        B3 -->|월~금 (1..5)| B4["main.py: NEIS 급식 조회 ➔ 카카오 발송"]
        B3 -->|토~일 (6..7)| B5["main.py --send-weekend-psalm: 시편 발송 ➔ 히스토리 커밋 ➔ GitHub Pages 배포"]
    end
```

- **트리거 인프라**: **Google Cloud Scheduler**
  - 작업 이름: `school-meal-daily`
  - 리전: `asia-northeast3` (서울)
  - 빈도: `30 6 * * *` (KST 매일 아침 06:30)
  - 호출 대상: `POST https://api.github.com/repos/jinugkim/school-meal/actions/workflows/meal_daily.yml/dispatches`
- **정시성**: GitHub Actions 내장 크론 큐의 지연을 우회하여 **매일 아침 6시 30분에 1~2분 내로 정확히 발송**됨.

---

## 3. 카카오톡 인증 및 토큰 자동 갱신 구조
- **독립형 자체 발송**: 중앙 라우터(`courier`)를 거치지 않고 `school-meal` 내부의 `main.py`가 카카오 OAuth 토큰 관리 및 발송을 직접 수행함.
- **토큰 자동 로테이션**:
  - 카카오 refresh token은 2개월 유효기간을 가지며, 만료 1개월 전부터 갱신 시 새 refresh token이 발급됨.
  - 새 refresh token이 발급되면 `update_github_secret()` 함수가 `PyNaCl`을 사용하여 **GitHub Actions 저장소 Secret을 자동으로 최신화**함. (수동 토큰 교체 필요 없음)
  - 토큰 갱신 실패 등 시스템 오류 발생 시 본인 계정으로만 기술 안내 알림이 전송됨.

---

## 4. 핵심 파일 및 역할
- `.github/workflows/meal_daily.yml`:
  - KST 기준 요일(`TZ=Asia/Seoul date +%u`) 자동 판별 스텝 내장
  - 평일 급식 발송 / 주말 시편 발송 자동 분기 실행
- `main.py`: 급식 수집(NEIS), 카카오톡 발송, 주말 시편 발송, GitHub Secret 자동 갱신 전체 로직
- `build_psalm_page.py`: 주말 시편 발송 히스토리를 정적 HTML 웹페이지(`_site`)로 빌드
- `weekend_psalms.md`: 55주차 주말 시편 구절 목록
- `data/weekend_psalm_history.json`: 발송된 주말 시편의 날짜별 아카이브 데이터
- `get_tokens.py`: 최초 카카오 토큰 발급 및 로컬 수동 갱신용 Flask 서버

---

## 5. 저장소 GitHub Secrets 레퍼런스
- `NEIS_API_KEY`: 나이스 교육정보 개방포털 인증키
- `OFFICE_CODE`: 서울특별시교육청 코드 (`B10`)
- `SCHOOL_CODE`: 대원국제중학교 코드 (`7130166`)
- `KAKAO_REST_API_KEY`: 카카오 Developers REST API 키
- `KAKAO_CLIENT_SECRET`: 카카오 Client Secret (설정된 경우)
- `KAKAO_REFRESH_TOKEN_ME`: 본인 카카오 refresh token
- `KAKAO_REFRESH_TOKEN_WIFE`: 배우자 카카오 refresh token
- `KAKAO_REFRESH_TOKEN_DAUGHTER`: 딸 카카오 refresh token
- `GH_TOKEN`: GitHub Secret 자동 갱신용 권한 토큰 (Actions 내장 `github.token`)
