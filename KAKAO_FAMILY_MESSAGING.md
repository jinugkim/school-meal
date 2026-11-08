# 카카오 가족 메시지 개발 경과와 현재 구조

작성 기준일: 2026-10-13

## 요약

배우자와 딸에게 급식 메시지를 보내기 위해 카카오 친구 목록에서 UUID를 찾아 친구 메시지 API를 사용하는 방식을 검토했습니다. 하지만 현재 앱 상태에서는 `friends` 동의항목 사용에 정책상 제약이 있어 진행할 수 없었습니다. 따라서 각 가족이 자기 카카오 계정으로 발급한 refresh token을 개별 GitHub Secret에 저장하고, 각 계정의 **나와의 채팅**으로 메시지를 보내는 구조로 전환했습니다.

이 방식은 친구 UUID나 친구 메시지 API를 사용하지 않습니다. 가족 각자가 앱에서 로그인하고 메시지 전송에 동의해야 하며, 해당 가족 계정의 refresh token이 필요합니다.

현재는 본인·배우자·딸 계정별 토큰으로 급식 메시지가 도착하는 것까지 확인했습니다.

## 개발 중 확인한 문제

### 1. 팀 멤버 등록만으로 친구 UUID를 읽을 수 없음

앱 팀 멤버 등록은 친구 목록 접근 권한이나 카카오 로그인 동의를 대신하지 않습니다. 친구 목록 API에서 가족의 UUID를 조회하려면 발신자 계정의 access token에 `friends` scope가 필요하고, 친구 메시지 전송에도 별도의 API 사용 조건이 적용됩니다.

### 2. 친구 목록 API가 `friends` scope 부족으로 거부됨

친구 목록 API 호출에서 다음 응답을 확인했습니다.

```text
403: -402; insufficient scopes.; 필요 동의항목: friends
```

카카오 Developers에서 `friends` 동의항목 설정·신청을 확인하는 과정에서 다음 정책 안내도 확인했습니다.

> 이 앱은 비즈 앱이 아닙니다. 비즈 앱으로 전환 후 신청 자격을 확인할 수 있습니다.

따라서 가족이 앱 팀 멤버이고 필요한 로그인 동의를 하더라도, 현재 앱의 정책상 `friends` scope를 사용할 수 없는 상태에서는 UUID 조회가 되지 않습니다. UUID를 임의로 입력하거나 프로필 식별자로 대체하는 방식도 사용할 수 없습니다.

### 3. 카카오톡 메시지 동의와 토큰 설정도 별도로 필요

초기 설정 중에는 `talk_message` 동의와 REST API 키/Client Secret이 맞지 않아 메시지 또는 토큰 요청이 거부되는 경우도 있었습니다. 기록된 주요 오류는 다음과 같습니다.

| 오류 | 확인된 원인과 조치 |
| --- | --- |
| KOE004 | Kakao Developers 앱의 카카오 로그인 설정 문제. 앱 설정을 확인해야 합니다. |
| `invalid_client` | 토큰을 발급한 앱과 Actions의 REST API 키 또는 Client Secret이 일치하지 않는 경우. 같은 앱의 값을 사용하도록 맞춥니다. |
| `expired_or_invalid_refresh_token` | 만료되었거나 이미 교체·폐기된 refresh token. 해당 가족 계정으로 다시 발급하고 그 계정의 Secret을 교체합니다. |
| 메시지 API 403 | `talk_message` 동의나 앱의 메시지 기능 설정을 점검해야 합니다. 현재 사용자는 본인 계정으로 메시지 도착을 확인했습니다. |

토큰 발급 동의와 메시지 API 사용은 서로 다른 확인 단계입니다. 각 계정으로 로그인·동의를 완료하고, 같은 Kakao 앱의 REST API 키와 필요한 Client Secret을 사용해야 합니다.

## 현재 적용한 방식

### 계정별 토큰

각 사용자가 `get_tokens.py`를 로컬에서 실행하고 자기 카카오 계정으로 로그인해 refresh token을 발급합니다. 토큰은 코드나 문서에 기록하지 않고 GitHub Actions Secrets에 저장합니다.

| Secret | 메시지를 받는 계정 |
| --- | --- |
| `KAKAO_REFRESH_TOKEN_ME` | 본인 |
| `KAKAO_REFRESH_TOKEN_WIFE` | 배우자 |
| `KAKAO_REFRESH_TOKEN_DAUGHTER` | 딸 |

설정된 Secret마다 해당 계정의 토큰으로 Kakao 나와의 채팅 메시지를 별도로 보냅니다. 가족 토큰이 만료되거나 전송에 실패해도 나머지 계정은 계속 처리하며, 일부 계정 실패는 GitHub Actions 실행 실패로 표시됩니다.

기존 `KAKAO_REFRESH_TOKENS` 배열은 가족별 Secret이 하나도 없을 때 사용하는 호환 경로로 남아 있습니다. 가족별 Secret이 하나라도 설정되면 배열은 사용되지 않습니다.

### 발송 대상 메시지

- 급식 메뉴는 설정된 가족 계정마다 보냅니다. 현재 예약은 평일 오전 2시 25분(KST)이며, 급식 대상일이 주말·한국 공휴일이면 급식 조회와 발송을 건너뜁니다. 화요일·목요일에는 해당하는 석식도 별도 메시지로 보냅니다.
- 토요일·일요일 오전 3시(KST)의 시편 메시지도 설정된 가족 계정마다 보냅니다.
- refresh token 교체, NEIS 오류, Kakao 전송 실패 등 기술 안내는 본인 계정에만 보냅니다. 배우자와 딸에게는 급식·시편 내용만 보냅니다.

### 토큰 교체 처리

Kakao 응답에서 새 refresh token이 발급되면 프로그램은 GitHub API로 해당 계정의 Actions Secret을 자동 교체합니다. 새 토큰은 로그나 안내 메시지에 표시하지 않습니다. 저장에 실패하면 Actions 실행 로그에 오류가 남으며, 해당 계정 Secret을 수동으로 재발급·교체해야 합니다. 이를 위해 `meal_daily.yml` 워크플로의 `GITHUB_TOKEN`에 `actions: write` 권한을 부여합니다.

## UUID 방식과 현재 방식 비교

| 항목 | 친구 UUID 방식 | 가족별 refresh token 방식 |
| --- | --- | --- |
| 메시지 API | 친구 목록 조회 후 친구에게 전송 | 각 계정이 자기 나와의 채팅으로 전송 |
| 가족별 UUID | `friends` scope로 조회 필요 | 사용하지 않음 |
| 현재 앱에서의 상태 | 비즈 앱 전환·scope 정책 제약으로 보류 | 이미 계정별 발급·테스트한 방식 |
| 관리할 값 | 발신자 토큰과 가족 UUID | 가족 구성원마다 refresh token Secret 하나 |
| 실패 영향 | 친구 목록 권한이나 수신자 식별에 영향 | 실패한 계정은 건너뛰고 다른 계정 처리 지속 |

## 운영 시 확인 위치

- GitHub **Settings → Secrets and variables → Actions**에서 계정별 Secret 이름을 확인합니다. Secret의 실제 값은 화면에서 다시 읽을 수 없으므로, 잘못 설정했으면 올바른 계정으로 새 토큰을 발급해 덮어씁니다.
- GitHub **Actions → Daily school meal**에서 실행 결과를 확인합니다. 로그와 Job summary에 대상 날짜, 메시지 종류, 계정별 성공·실패가 표시됩니다.
- 토큰 재발급 절차는 [README의 Refresh token 갱신 안내](README.md#refresh-token-갱신)를 참고합니다.
