"""Unit tests for ``lib.zadarma_client``.

Framework-independent — no Odoo runtime required. Run with plain pytest:
    python -m pytest tests/ -v
"""

import base64
import hashlib
import hmac

from lib.zadarma_client import (
    compute_signature,
    compute_webhook_signatures,
    is_rate_limited,
    normalize_phone,
    normalize_status,
    verify_webhook_signature,
)

SECRET = 'test-secret-do-not-use-in-prod'


class TestComputeSignature:
    def test_matches_reference_implementation(self):
        query_string, signature = compute_signature(
            SECRET, '/v1/info/balance/', {'b': '2', 'a': '1'}
        )
        assert query_string == 'a=1&b=2'
        md5_hex = hashlib.md5(query_string.encode(), usedforsecurity=False).hexdigest()
        sign_str = '/v1/info/balance/' + query_string + md5_hex
        expected = base64.b64encode(
            hmac.new(SECRET.encode(), sign_str.encode(), hashlib.sha1).hexdigest().encode()
        ).decode()
        assert signature == expected

    def test_empty_params_still_signs(self):
        query_string, signature = compute_signature(SECRET, '/v1/info/balance/', {})
        assert query_string == ''
        assert signature  # non-empty, deterministic

    def test_deterministic_for_same_input(self):
        first = compute_signature(SECRET, '/v1/pbx/record/request/', {'call_id': 'abc123'})
        second = compute_signature(SECRET, '/v1/pbx/record/request/', {'call_id': 'abc123'})
        assert first == second


class TestIsRateLimited:
    def test_http_429_is_rate_limited(self):
        assert is_rate_limited(429, None) is True

    def test_http_200_with_rate_limit_message(self):
        body = {'status': 'error', 'message': 'You exceeded the rate limit by User Limits'}
        assert is_rate_limited(200, body) is True

    def test_http_200_success_is_not_rate_limited(self):
        assert is_rate_limited(200, {'status': 'success'}) is False

    def test_http_200_other_error_is_not_rate_limited(self):
        assert is_rate_limited(200, {'status': 'error', 'message': 'invalid signature'}) is False

    def test_missing_body_is_not_rate_limited(self):
        assert is_rate_limited(200, None) is False


class TestNormalizePhone:
    def test_strips_formatting(self):
        assert normalize_phone('+48 (123) 456-789') == '48123456789'

    def test_empty_input(self):
        assert normalize_phone('') == ''
        assert normalize_phone(None) == ''

    def test_already_digits_only(self):
        assert normalize_phone('48123456789') == '48123456789'


class TestNormalizeStatus:
    WHITELIST = frozenset({'answered', 'no answer', 'cancel', 'busy'})

    def test_known_status_passthrough(self):
        assert normalize_status('answered', self.WHITELIST, 'failed') == 'answered'

    def test_case_and_whitespace_insensitive(self):
        assert normalize_status('  ANSWERED  ', self.WHITELIST, 'failed') == 'answered'

    def test_unknown_status_falls_back(self):
        assert normalize_status('voicemail', self.WHITELIST, 'failed') == 'failed'

    def test_empty_returns_false(self):
        assert normalize_status(None, self.WHITELIST, 'failed') is False
        assert normalize_status('', self.WHITELIST, 'failed') is False


class TestWebhookSignatureVerification:
    def test_variant_a_match(self):
        params_string = 'call_id=test123&event=NOTIFY_END'
        sig_a, _sig_b = compute_webhook_signatures(SECRET, params_string)
        assert verify_webhook_signature(SECRET, params_string, sig_a) == 'A'

    def test_variant_b_match(self):
        params_string = 'call_id=test123&event=NOTIFY_END'
        _sig_a, sig_b = compute_webhook_signatures(SECRET, params_string)
        assert verify_webhook_signature(SECRET, params_string, sig_b) == 'B'

    def test_no_match_returns_none(self):
        params_string = 'call_id=test123&event=NOTIFY_END'
        assert verify_webhook_signature(SECRET, params_string, 'bogus-signature') is None

    def test_tampered_params_break_the_signature(self):
        original = 'call_id=test123&event=NOTIFY_END'
        tampered = 'call_id=test999&event=NOTIFY_END'
        sig_a, _ = compute_webhook_signatures(SECRET, original)
        assert verify_webhook_signature(SECRET, tampered, sig_a) is None
