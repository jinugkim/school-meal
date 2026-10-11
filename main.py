"""Fetch today's NEIS meal and send a KakaoTalk memo to each configured recipient."""

import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
NEIS_URL = "https://open.neis.go.kr/hub/mealServiceDietInfo"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


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


def format_meal_message(date_label, day_label, meals):
    title = f"🍚 {date_label} {day_label}의 급식"
    sections = []
    for name, dishes, calories in meals:
        content = " · ".join(dishes)
        if calories:
            content += f" (열량 {calories})"
        sections.append((name, content))

    message = title + "\n\n" + "\n\n".join(
        f"【{name}】\n{content}" for name, content in sections
    )
    if len(message) <= 200:
        return message

    # Kakao's text template has a 200-character limit. On longer menus,
    # reserve room for every meal heading so dinner is not silently omitted.
    prefix = title + "\n"
    labels = [f"【{name}】 " for name, _ in sections]
    separators_length = max(0, len(sections) - 1)
    content_budget = max(0, 200 - len(prefix) - sum(map(len, labels)) - separators_length)
    per_section_budget = content_budget // max(1, len(sections))
    compact_sections = []
    for (name, content), label in zip(sections, labels):
        if len(content) > per_section_budget and per_section_budget:
            content = content[: per_section_budget - 1] + "…"
        else:
            content = content[:per_section_budget]
        compact_sections.append(label + content)
    return prefix + "\n".join(compact_sections)


def get_access_token(refresh_token, rest_api_key, client_secret=""):
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
        logger.warning("Kakao refresh token rotated; update KAKAO_REFRESH_TOKENS secret with the new value.")
    return token, refresh_token_rotated


def send_kakao_message(access_token, message):
    template = {
        "object_type": "text",
        "text": message[:200],
        "link": {"web_url": "https://open.neis.go.kr", "mobile_web_url": "https://open.neis.go.kr"},
        "button_title": "나이스 급식 정보",
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
    raw = required_env("KAKAO_REFRESH_TOKENS")
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
    return tokens


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
    meal_day = today + timedelta(days=day_offset)
    meal_date = meal_day.strftime("%Y%m%d")
    date_label = meal_day.strftime("%Y년 %m월 %d일")
    meal_day_label = "내일" if day_offset == 1 else "오늘"
    is_scheduled = os.environ.get("GITHUB_EVENT_NAME") == "schedule"

    # Query and report NEIS before checking Kakao settings so the data source
    # can be verified independently during initial setup.
    try:
        meals = get_today_meal(api_key, office_code, school_code, meal_date)
        if meals:
            message = format_meal_message(date_label, meal_day_label, meals)
            logger.info("NEIS 급식 조회 완료 (%d개 식사 구분):", len(meals))
            for name, dishes, calories in meals:
                logger.info("%s: %s", name, " / ".join(dishes))
                if calories:
                    logger.info("열량: %s", calories)
        else:
            logger.info("NEIS 조회 완료: %s 등록된 급식 정보가 없습니다.", date_label)
            if is_scheduled:
                logger.info("예약 실행이며 급식 정보가 없어 카카오 메시지 전송을 건너뜁니다.")
                return 0
            message = f"🍚 테스트 메시지입니다. {date_label} 등록된 급식 정보가 없습니다."
    except Exception:
        logger.exception("NEIS 급식 조회 실패")
        message = f"🍚 {date_label} 급식 정보를 가져오지 못했습니다. 잠시 후 NEIS 서비스 상태를 확인해 주세요."

    kakao_key = required_env("KAKAO_REST_API_KEY")
    tokens = load_refresh_tokens()
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()

    failures = 0
    for index, refresh_token in enumerate(tokens, start=1):
        try:
            access_token, refresh_token_rotated = get_access_token(refresh_token, kakao_key, client_secret)
            recipient_message = message
            if refresh_token_rotated:
                recipient_message = (
                    "⚠️ 카카오 인증 정보 갱신이 필요합니다. "
                    "새 refresh token을 발급해 GitHub Secret KAKAO_REFRESH_TOKENS를 교체해 주세요.\n\n"
                    + message
                )
            send_kakao_message(access_token, recipient_message)
            logger.info("수신자 %d/%d 전송 완료", index, len(tokens))
        except Exception:
            failures += 1
            logger.exception("수신자 %d/%d 전송 실패; 다음 계정을 계속 처리합니다.", index, len(tokens))
    if failures == len(tokens):
        return 1
    if failures:
        logger.warning("%d/%d 계정에서 전송이 실패했습니다.", failures, len(tokens))
    return 0


if __name__ == "__main__":
    try:
        if "--check-neis" in sys.argv[1:]:
            sys.exit(check_neis())
        sys.exit(main())
    except (ValueError, requests.RequestException) as exc:
        logger.error("실행 설정 또는 서비스 요청 오류: %s", exc)
        sys.exit(1)
