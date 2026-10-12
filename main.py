"""Fetch today's NEIS meal and send a KakaoTalk memo to each configured recipient."""

import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import holidays

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
NEIS_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
WEEKEND_PSALM_START = date(2026, 10, 17)


def clean_dish_name(value):
    """Turn NEIS HTML breaks into lines and remove allergy marker numbers."""
    value = re.sub(r"<br\s*/?>", "\n", str(value), flags=re.IGNORECASE)
    value = re.sub(r"\([^)]*\)", lambda m: re.sub(r"\d+(?:\.\d+)*\.?", "", m.group(0)), value)
    value = re.sub(r"\(\s*\)", "", value)
    value = re.sub(r"\d+(?:\.\d+)*\.(?=\s|$)", "", value)
    return re.sub(r"[ \t]+", " ", value).strip()


def required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"필수 환경 변수가 설정되지 않았습니다: {name}")
    return value


def get_today_meal(api_key, office_code, school_code, meal_date=None):
    """Return meals grouped by NEIS meal name; an empty list means no meal data."""
    date = meal_date or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    response = requests.get(
        NEIS_URL,
        params={
            "KEY": api_key, "Type": "json", "pIndex": 1, "pSize": 100,
            "ATPT_OFCDC_SC_CODE": office_code, "SD_SCHUL_CODE": school_code,
            "MLSV_YMD": date,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if "mealServiceDietInfo" not in payload:
        # NEIS returns RESULT when the query is valid but there are no rows.
        result = payload.get("RESULT", {})
        if result.get("CODE") in {"INFO-200", "INFO-201"}:
            return []
        raise RuntimeError(f"NEIS 응답에 급식 정보가 없습니다: {result.get('MESSAGE', '알 수 없는 응답')}")

    rows = payload["mealServiceDietInfo"][-1].get("row", [])
    meals = {}
    for row in rows:
        meal_name = str(row.get("MMEAL_SC_NM", "")).strip() or "급식"
        meal = meals.setdefault(meal_name, {"menu": [], "calories": []})
        raw = row.get("DDISH_NM", "")
        meal["menu"].extend(line.strip() for line in clean_dish_name(raw).splitlines() if line.strip())
        calorie = row.get("CAL_INFO", "")
        if calorie:
            meal["calories"].append(str(calorie).strip())
    return [
        (name, details["menu"], " / ".join(dict.fromkeys(details["calories"])))
        for name, details in meals.items()
        if details["menu"]
    ]


def format_meal_message(date_label, day_label, meal):
    name, dishes, calories = meal
    title = f"🍚 {date_label} {day_label} {name}"
    content = "\n".join(f"• {dish}" for dish in dishes)
    if calories:
        content += f"\n열량: {calories}"
    message = f"{title}\n\n{content}"
    if len(message) <= 200:
        return message
    # Kakao's text template is limited to 200 characters.
    return message[:199] + "…"


def meals_for_scheduled_day(meals, meal_day):
    """Keep dinner only on non-holiday Tuesdays and Thursdays."""
    korea_holidays = holidays.country_holidays(
        "KR", years=[meal_day.year], categories=holidays.PUBLIC
    )
    holiday_name = korea_holidays.get(meal_day)
    dinner_day = meal_day.weekday() in (1, 3) and not holiday_name
    if holiday_name:
        logger.info("%s은(는) 한국 공휴일(%s)이라 석식 발송을 건너뜁니다.", meal_day.strftime("%Y-%m-%d"), holiday_name)
    elif meal_day.weekday() not in (1, 3):
        logger.info("화요일·목요일이 아니므로 석식 발송을 건너뜁니다.")
    return [meal for meal in meals if meal[0] != "석식" or dinner_day]


def get_access_token(refresh_token, rest_api_key, client_secret="", secret_name="KAKAO_REFRESH_TOKENS"):
    data = {"grant_type": "refresh_token", "client_id": rest_api_key, "refresh_token": refresh_token}
    if client_secret:
        data["client_secret"] = client_secret
    response = requests.post(KAKAO_TOKEN_URL, data=data, timeout=20)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        # Kakao's response identifies issues such as invalid_grant or
        # invalid_client. Log only its error fields, never request credentials.
        try:
            error_info = response.json()
        except ValueError:
            error_info = {}
        error = error_info.get("error", "")
        description = error_info.get("error_description", "")
        detail = ": ".join(value for value in (error, description) if value)
        if detail:
            raise RuntimeError(f"카카오 토큰 갱신 실패 ({response.status_code}): {detail}") from exc
        raise
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("카카오 토큰 응답에 access_token이 없습니다.")
    # Kakao may rotate refresh tokens. The new value must be saved back to the repository secret.
    refresh_token_rotated = bool(payload.get("refresh_token"))
    if refresh_token_rotated:
        logger.warning("Kakao refresh token rotated; update %s secret with the new value.", secret_name)
    return token, refresh_token_rotated


def send_kakao_message(
    access_token,
    message,
    link_url="https://open.neis.go.kr",
    button_title="나이스 급식 정보",
):
    template = {
        "object_type": "text",
        "text": message[:200],
        "link": {"web_url": link_url, "mobile_web_url": link_url},
        "button_title": button_title,
    }
    response = requests.post(
        KAKAO_MEMO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        timeout=20,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            error_info = response.json()
        except ValueError:
            error_info = {}
        code = error_info.get("code", "")
        message = error_info.get("msg", "")
        scopes = error_info.get("required_scopes", [])
        details = [str(value) for value in (code, message) if value != ""]
        if scopes:
            details.append(f"필요 동의항목: {', '.join(scopes)}")
        if details:
            raise RuntimeError(f"카카오 메시지 전송 실패 ({response.status_code}): {'; '.join(details)}") from exc
        raise
    result = response.json()
    if result.get("result_code") != 0:
        raise RuntimeError(f"카카오 메시지 전송 실패: {result}")


def load_refresh_tokens():
    individual_secrets = [
        ("본인", "KAKAO_REFRESH_TOKEN_ME"),
        ("배우자", "KAKAO_REFRESH_TOKEN_WIFE"),
        ("딸", "KAKAO_REFRESH_TOKEN_DAUGHTER"),
    ]
    recipients = [
        (label, secret_name, os.environ.get(secret_name, "").strip())
        for label, secret_name in individual_secrets
        if os.environ.get(secret_name, "").strip()
    ]
    if recipients:
        return recipients

    raw = os.environ.get("KAKAO_REFRESH_TOKENS", "").strip()
    if not raw:
        expected = ", ".join(secret_name for _, secret_name in individual_secrets)
        raise ValueError(f"가족별 Kakao refresh token Secret을 설정하세요: {expected}")
    try:
        values = json.loads(raw)
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        values = raw.split(",")
    tokens = [str(token).strip() for token in values if str(token).strip()]
    if not tokens:
        raise ValueError("KAKAO_REFRESH_TOKENS에 유효한 토큰이 없습니다.")
    logger.warning("KAKAO_REFRESH_TOKENS 배열 사용 중입니다. 가족별 Secret으로 옮기면 갱신이 더 간단합니다.")
    return [(f"계정 {index}", "KAKAO_REFRESH_TOKENS", token) for index, token in enumerate(tokens, start=1)]


def load_weekend_psalm_weeks():
    """Read the curated Saturday/Sunday messages from the human-readable list."""
    path = os.path.join(os.path.dirname(__file__), "weekend_psalms.md")
    row_pattern = re.compile(r"^\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$")
    message_pattern = re.compile(r"^(.*?)\s+—\s+(Psalm\s+\d+:\d+(?:[–-]\d+)?)\s+\(WEB Updated\)$")
    weeks = []
    with open(path, encoding="utf-8") as source:
        for line in source:
            row = row_pattern.match(line.rstrip("\n"))
            if not row:
                continue
            week_number = int(row.group(1))
            if week_number != len(weeks) + 1:
                raise ValueError("주말 시편 목록의 주차 번호가 순서대로 이어지지 않습니다.")
            messages = []
            for cell in row.group(2, 3):
                item = message_pattern.match(cell.strip())
                if not item:
                    raise ValueError(f"주말 시편 목록 {week_number}주차 형식이 잘못되었습니다.")
                message = f"{item.group(1)}\n— {item.group(2)}"
                if len(message) > 200:
                    raise ValueError(f"주말 시편 목록 {week_number}주차 메시지가 200자를 넘습니다.")
                messages.append(message)
            weeks.append(tuple(messages))
    if len(weeks) != 55:
        raise ValueError(f"주말 시편 목록은 55주가 필요하지만 {len(weeks)}주만 있습니다.")
    return weeks


def send_weekend_psalm():
    """Send the scheduled weekend Psalm to the owner's Kakao account."""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    today = now.date()
    if today.weekday() not in (5, 6):
        logger.info("주말 시편 예약일이 아니므로 발송하지 않습니다.")
        return 0
    if today < WEEKEND_PSALM_START:
        logger.info("주말 시편 발송 시작일(%s) 전이므로 건너뜁니다.", WEEKEND_PSALM_START)
        return 0

    weeks = load_weekend_psalm_weeks()
    week_index = ((today - WEEKEND_PSALM_START).days // 7) % len(weeks)
    week_number = week_index + 1
    message_index = 0 if today.weekday() == 5 else 1
    message = weeks[week_index][message_index]
    logger.info(
        "주말 시편 발송: %s KST, %d주차 %s 구절",
        now.strftime("%Y-%m-%d %H:%M:%S"),
        week_number,
        "토요일" if message_index == 0 else "일요일",
    )

    kakao_key = required_env("KAKAO_REST_API_KEY")
    recipients = load_refresh_tokens()
    owner = next((entry for entry in recipients if entry[1] == "KAKAO_REFRESH_TOKEN_ME"), None)
    if owner is None:
        raise ValueError("주말 시편 발송에는 KAKAO_REFRESH_TOKEN_ME Secret이 필요합니다.")
    _, secret_name, refresh_token = owner
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
    technical_alerts = []
    try:
        access_token, refresh_token_rotated = get_access_token(
            refresh_token, kakao_key, client_secret, secret_name
        )
    except Exception:
        logger.exception("본인 계정의 주말 시편 발송용 토큰 갱신에 실패했습니다.")
        return 1

    failures = 0
    try:
        send_kakao_message(
            access_token,
            message,
            link_url="https://ebible.org/engwebu/",
            button_title="Psalms",
        )
        logger.info("본인 계정으로 주말 시편 전송 완료")
    except Exception:
        failures += 1
        logger.exception("본인 계정으로 주말 시편 전송에 실패했습니다.")
        technical_alerts.append("주말 시편 메시지를 보내지 못했습니다. GitHub Actions 로그를 확인해 주세요.")

    if refresh_token_rotated:
        technical_alerts.append(
            f"본인 계정 refresh token이 교체됐습니다. 새 토큰을 발급해 GitHub Secret {secret_name}을 갱신해 주세요."
        )

    if technical_alerts:
        for alert in dict.fromkeys(technical_alerts):
            try:
                send_kakao_message(access_token, f"⚠️ 급식 알림 시스템 안내\n{alert}")
                logger.info("운영 안내를 본인 계정으로 전송했습니다.")
            except Exception:
                failures += 1
                logger.exception("본인 계정으로 운영 안내를 전송하지 못했습니다.")

    return 1 if failures else 0


def check_neis():
    """Query NEIS and print the result without requiring Kakao credentials."""
    api_key = required_env("NEIS_API_KEY")
    office_code = required_env("OFFICE_CODE")
    school_code = required_env("SCHOOL_CODE")

    today = datetime.now(ZoneInfo("Asia/Seoul"))
    meals = get_today_meal(api_key, office_code, school_code)
    logger.info("NEIS 조회 날짜: %s", today.strftime("%Y-%m-%d"))
    if not meals:
        logger.info("오늘 등록된 급식 정보가 없습니다.")
        return 0
    for name, dishes, calories in meals:
        logger.info("%s:\n%s", name, "\n".join(f"• {dish}" for dish in dishes))
        if calories:
            logger.info("열량: %s", calories)
    return 0


def main():
    api_key = required_env("NEIS_API_KEY")
    office_code = required_env("OFFICE_CODE")
    school_code = required_env("SCHOOL_CODE")
    today = datetime.now(ZoneInfo("Asia/Seoul"))
    day_offset = int(os.environ.get("MEAL_DAY_OFFSET", "0"))
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    is_scheduled = event_name == "schedule"
    if event_name == "workflow_dispatch" and today.weekday() >= 5:
        day_offset = 7 - today.weekday()
    meal_day = today + timedelta(days=day_offset)
    meal_date = meal_day.strftime("%Y%m%d")
    date_label = meal_day.strftime("%Y년 %m월 %d일")
    if day_offset and meal_day.weekday() == 0 and today.weekday() >= 5:
        meal_day_label = "월요일"
    else:
        meal_day_label = "내일" if day_offset == 1 else "오늘"
    logger.info(
        "실행 시각(KST): %s; 실행 유형: %s; 조회 대상일: %s",
        today.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "예약" if is_scheduled else "수동/로컬",
        meal_day.strftime("%Y-%m-%d"),
    )

    # Query and report NEIS before checking Kakao settings so the data source
    # can be verified independently during initial setup.
    technical_alerts = []
    neis_failed = False
    try:
        meals = get_today_meal(api_key, office_code, school_code, meal_date)
        if meals:
            meals = meals_for_scheduled_day(meals, meal_day)
            if not meals:
                logger.info("발송 대상 급식이 없어 카카오 메시지를 보내지 않습니다.")
                return 0
            logger.info("NEIS 급식 조회 완료 (%d개 식사 구분):", len(meals))
            for name, dishes, calories in meals:
                logger.info("%s: %s", name, " / ".join(dishes))
                if calories:
                    logger.info("열량: %s", calories)
            messages = [
                format_meal_message(date_label, meal_day_label, meal)
                for meal in meals
            ]
        else:
            logger.info("NEIS 조회 완료: %s 등록된 급식 정보가 없습니다.", date_label)
            if is_scheduled:
                logger.info("예약 실행이며 급식 정보가 없어 카카오 메시지 전송을 건너뜁니다.")
                return 0
            technical_alerts.append(f"수동 실행 확인: {date_label} NEIS에 등록된 급식 정보가 없습니다.")
            messages = []
    except Exception:
        logger.exception("NEIS 급식 조회 실패")
        technical_alerts.append(f"NEIS 급식 조회에 실패했습니다 ({date_label}). GitHub Actions 로그를 확인해 주세요.")
        messages = []
        neis_failed = True

    kakao_key = required_env("KAKAO_REST_API_KEY")
    recipients = load_refresh_tokens()
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()

    failures = 0
    account_access_tokens = {}
    for index, (recipient_name, secret_name, refresh_token) in enumerate(recipients, start=1):
        try:
            access_token, refresh_token_rotated = get_access_token(
                refresh_token, kakao_key, client_secret, secret_name
            )
            account_access_tokens[recipient_name] = access_token
        except Exception:
            failures += 1
            logger.exception("수신자 %s (%d/%d) 토큰 갱신 실패; 다음 계정을 계속 처리합니다.", recipient_name, index, len(recipients))
            technical_alerts.append(f"{recipient_name} 계정의 카카오 토큰 갱신에 실패했습니다. {secret_name}과 Actions 로그를 확인해 주세요.")
            continue

        recipient_failed = False
        for message_index, message in enumerate(messages, start=1):
            try:
                send_kakao_message(access_token, message)
                logger.info("수신자 %s (%d/%d) 메시지 %d/%d 전송 완료", recipient_name, index, len(recipients), message_index, len(messages))
            except Exception:
                recipient_failed = True
                logger.exception(
                    "수신자 %s (%d/%d) 메시지 %d/%d 전송 실패; 다음 메시지를 계속 처리합니다.",
                    recipient_name, index, len(recipients), message_index, len(messages),
                )
                technical_alerts.append(f"{recipient_name} 계정으로 급식 메시지를 보내지 못했습니다. Actions 로그를 확인해 주세요.")

        if refresh_token_rotated:
            technical_alerts.append(
                f"{recipient_name} 계정 refresh token이 교체됐습니다. 새 토큰을 발급해 GitHub Secret {secret_name}을 갱신해 주세요."
            )

        if recipient_failed:
            failures += 1
    if failures:
        logger.warning("%d/%d 계정에서 전송이 실패했습니다.", failures, len(recipients))

    # Operational and credential notices go only to the owner's Kakao account.
    owner_access_token = account_access_tokens.get("본인")
    if technical_alerts and owner_access_token:
        for alert in dict.fromkeys(technical_alerts):
            try:
                send_kakao_message(owner_access_token, f"⚠️ 급식 알림 시스템 안내\n{alert}")
                logger.info("운영 안내를 본인 계정으로 전송했습니다.")
            except Exception:
                failures += 1
                logger.exception("본인 계정으로 운영 안내를 전송하지 못했습니다.")
    elif technical_alerts:
        logger.warning("본인 계정 Secret이 없어 기술 안내를 카카오로 보내지 못했습니다.")
        failures += 1

    return 1 if failures or neis_failed else 0


if __name__ == "__main__":
    try:
        if "--send-weekend-psalm" in sys.argv[1:]:
            sys.exit(send_weekend_psalm())
        if "--check-neis" in sys.argv[1:]:
            sys.exit(check_neis())
        sys.exit(main())
    except (ValueError, requests.RequestException) as exc:
        logger.error("실행 설정 또는 서비스 요청 오류: %s", exc)
        sys.exit(1)
