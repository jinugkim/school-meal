"""Fetch today's NEIS meal and send a KakaoTalk memo to each configured recipient."""

import json
import logging
import os
import re
import sys
from datetime import datetime
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
    """Return (menu, calories); an empty menu means no meal data was published."""
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
            return [], ""
        raise RuntimeError(f"NEIS 응답에 급식 정보가 없습니다: {result.get('MESSAGE', '알 수 없는 응답')}")

    rows = payload["mealServiceDietInfo"][-1].get("row", [])
    menu, calories = [], []
    for row in rows:
        raw = row.get("DDISH_NM", "")
        menu.extend(line.strip() for line in clean_dish_name(raw).splitlines() if line.strip())
        calorie = row.get("CAL_INFO", "")
        if calorie:
            calories.append(str(calorie).strip())
    return menu, " / ".join(dict.fromkeys(calories))


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
    if payload.get("refresh_token"):
        logger.warning("Kakao refresh token rotated; update KAKAO_REFRESH_TOKENS secret with the new value.")
    return token


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
    response.raise_for_status()
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
    menu, calories = get_today_meal(api_key, office_code, school_code)
    logger.info("NEIS 조회 날짜: %s", today.strftime("%Y-%m-%d"))
    if not menu:
        logger.info("오늘 등록된 급식 정보가 없습니다.")
        return 0
    logger.info("오늘의 급식:\n%s", "\n".join(f"• {dish}" for dish in menu))
    if calories:
        logger.info("열량: %s", calories)
    return 0


def main():
    api_key = required_env("NEIS_API_KEY")
    office_code = required_env("OFFICE_CODE")
    school_code = required_env("SCHOOL_CODE")
    today = datetime.now(ZoneInfo("Asia/Seoul"))
    date_label = today.strftime("%Y년 %m월 %d일")

    # Query and report NEIS before checking Kakao settings so the data source
    # can be verified independently during initial setup.
    try:
        menu, calories = get_today_meal(api_key, office_code, school_code)
        if menu:
            message = f"🍚 {date_label} 오늘의 급식\n\n" + "\n".join(f"• {dish}" for dish in menu)
            if calories:
                message += f"\n\n열량: {calories}"
            logger.info("NEIS 급식 조회 완료:\n%s", "\n".join(f"• {dish}" for dish in menu))
            if calories:
                logger.info("열량: %s", calories)
        else:
            message = f"🍚 {date_label} 오늘은 등록된 급식 정보가 없습니다. (주말·공휴일·방학일 수 있습니다)"
            logger.info("NEIS 조회 완료: 오늘 등록된 급식 정보가 없습니다.")
    except Exception:
        logger.exception("NEIS 급식 조회 실패")
        message = f"🍚 {date_label} 급식 정보를 가져오지 못했습니다. 잠시 후 NEIS 서비스 상태를 확인해 주세요."

    kakao_key = required_env("KAKAO_REST_API_KEY")
    tokens = load_refresh_tokens()
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()

    failures = 0
    for index, refresh_token in enumerate(tokens, start=1):
        try:
            access_token = get_access_token(refresh_token, kakao_key, client_secret)
            send_kakao_message(access_token, message)
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
