"""The local-auth request contract: emails compare case-blind, passwords fit bcrypt's byte cap."""

from pydantic import ValidationError
import pytest

from app.models.auth_models import BCRYPT_MAX_PASSWORD_BYTES, LoginRequest, SignupRequest


def test_the_whole_email_is_lowercased_not_just_the_domain() -> None:
    assert LoginRequest(email="Admin@EXAMPLE.com", password="pw").email == "admin@example.com"


def test_a_password_of_exactly_the_byte_cap_is_accepted() -> None:
    password = "€" * 24  # 72 UTF-8 bytes in 24 characters

    assert len(password.encode("utf-8")) == BCRYPT_MAX_PASSWORD_BYTES
    assert SignupRequest(email="a@b.co", password=password).password == password


def test_a_password_over_the_byte_cap_is_refused_though_its_characters_fit() -> None:
    with pytest.raises(ValidationError) as refused:
        SignupRequest(email="a@b.co", password="€" * 25)  # 75 bytes, 25 characters

    [error] = refused.value.errors()
    assert error["loc"] == ("password",)
    assert error["msg"] == "Value error, Password must be at most 72 bytes when UTF-8 encoded"
