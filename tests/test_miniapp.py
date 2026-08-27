"""v0.11: Telegram Mini App & initData validation tests."""

from __future__ import annotations

import hashlib
import hmac
import time

from anbar.auth import verify_telegram_init_data


def test_verify_telegram_init_data():
    bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    auth_date = int(time.time())

    # Build valid initData
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": '{"id":279058397,"first_name":"Vladislav"}',
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    valid_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    init_data = (
        f"auth_date={params['auth_date']}&query_id={params['query_id']}"
        f"&user={params['user']}&hash={valid_hash}"
    )

    # 1. Valid signature passes
    assert verify_telegram_init_data(init_data, bot_token) is True

    # 2. Tampered data fails
    tampered = (
        f"auth_date={params['auth_date']}&query_id=hacked"
        f"&user={params['user']}&hash={valid_hash}"
    )
    assert verify_telegram_init_data(tampered, bot_token) is False

    # 3. Expired data fails
    old_params = dict(params)
    old_params["auth_date"] = str(auth_date - 100000)
    old_dcs = "\n".join(f"{k}={v}" for k, v in sorted(old_params.items()))
    old_hash = hmac.new(secret_key, old_dcs.encode(), hashlib.sha256).hexdigest()
    old_init_data = (
        f"auth_date={old_params['auth_date']}&query_id={old_params['query_id']}"
        f"&user={old_params['user']}&hash={old_hash}"
    )
    assert verify_telegram_init_data(old_init_data, bot_token, max_age_s=3600) is False


def test_telegram_miniapp_endpoint(client):
    r = client.get("/tg-app")
    assert r.status_code == 200
    assert "Telegram Mini App" in r.text
