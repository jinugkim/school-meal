"""Local-only Kakao OAuth helper for obtaining a family member's refresh token."""

import os
import secrets
from urllib.parse import urlencode

import requests
from flask import Flask, abort, request, session

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "").strip()
REDIRECT_URI = os.environ.get("KAKAO_REDIRECT_URI", "http://127.0.0.1:5000/oauth").strip()
CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


@app.get("/")
def index():
    if not REST_API_KEY:
        return page(
            "설정 필요",
            '<p><code>KAKAO_REST_API_KEY</code> 환경 변수를 설정한 뒤 서버를 다시 실행하세요.</p>',
        ), 400
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    query = urlencode({
        "client_id": REST_API_KEY,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "talk_message",
        "state": state,
    })
    return page(
        "카카오 refresh token 발급",
        "<p>발급받을 카카오 계정으로 로그인한 뒤 동의해 주세요. 토큰은 이 브라우저에만 표시됩니다.</p>"
        f'<p><a class="button" href="{AUTH_URL}?{query}">카카오 로그인</a></p>'
        "<p>카카오 개발자 콘솔의 Redirect URI에 아래 주소를 등록해야 합니다.</p>"
        f"<p><code>{escape_html(REDIRECT_URI)}</code></p>",
    )


@app.get("/oauth")
def oauth_callback():
    if request.args.get("error"):
        return page("로그인 취소", "<p>카카오 로그인이 취소되었거나 거부되었습니다.</p>"), 400
    expected_state = session.pop("oauth_state", None)
    if not expected_state or not secrets.compare_digest(expected_state, request.args.get("state", "")):
        abort(400, "OAuth state 검증에 실패했습니다. 처음부터 다시 시도하세요.")
    code = request.args.get("code")
    if not code:
        abort(400, "인가 코드가 없습니다.")
    if not REST_API_KEY:
        abort(500, "KAKAO_REST_API_KEY가 설정되지 않았습니다.")

    data = {
        "grant_type": "authorization_code",
        "client_id": REST_API_KEY,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }
    if CLIENT_SECRET:
        data["client_secret"] = CLIENT_SECRET
    try:
        response = requests.post(TOKEN_URL, data=data, timeout=20)
        response.raise_for_status()
        token_data = response.json()
    except (requests.RequestException, ValueError):
        app.logger.exception("Kakao token request failed")
        return page("토큰 발급 실패", "<p>토큰 요청에 실패했습니다. 설정과 Redirect URI를 확인하고 다시 시도하세요.</p>"), 502

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        return page("토큰 발급 실패", "<p>응답에 refresh token이 없습니다. 카카오 응답과 앱 설정을 확인하세요.</p>"), 502
    return page(
        "발급 완료",
        "<p>아래 토큰을 로그인한 계정에 해당하는 GitHub Secret에 안전하게 저장하세요. "
        "예: 본인 계정은 <code>KAKAO_REFRESH_TOKEN_ME</code>, 배우자는 "
        "<code>KAKAO_REFRESH_TOKEN_WIFE</code>, 딸은 <code>KAKAO_REFRESH_TOKEN_DAUGHTER</code>.</p>"
        f'<textarea readonly rows="5" onclick="this.select()">{escape_html(refresh_token)}</textarea>'
        "<p>토큰은 비밀번호와 같습니다. 저장 후 이 페이지를 닫고 공유하거나 저장소에 커밋하지 마세요.</p>",
    )


def escape_html(value):
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#x27;"))


def page(title, body):
    return (
        "<!doctype html><html lang='ko'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape_html(title)}</title><style>body{{font:16px sans-serif;max-width:680px;margin:4rem auto;padding:0 1rem;line-height:1.7}}"
        ".button{display:inline-block;background:#fee500;color:#191919;padding:.7rem 1.2rem;text-decoration:none;border-radius:8px}"
        "textarea{box-sizing:border-box;width:100%;padding:.8rem;word-break:break-all}</style>"
        f"<h1>{escape_html(title)}</h1>{body}</html>"
    )


if __name__ == "__main__":
    # Bind only to loopback: this helper handles credentials and is intended for local use.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
