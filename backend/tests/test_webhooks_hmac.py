import base64
import hashlib
import hmac

from scout.capture.webhooks import verify_hmac


def _sign(secret: str, body: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def test_valid_signature_accepted():
    secret, body = "shhh", b'{"id": 1}'
    assert verify_hmac(secret, body, _sign(secret, body)) is True


def test_forged_signature_rejected():
    assert verify_hmac("shhh", b'{"id": 1}', "not-the-signature") is False


def test_missing_secret_or_header_rejected():
    body = b"{}"
    assert verify_hmac("", body, _sign("shhh", body)) is False
    assert verify_hmac("shhh", body, None) is False
