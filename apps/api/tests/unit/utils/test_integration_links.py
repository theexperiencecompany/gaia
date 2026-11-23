"""The connect link the web integrations page turns into a started connect flow."""

from app.utils.integration_links import integration_connect_path


def test_a_new_connection_names_only_the_integration() -> None:
    assert integration_connect_path("gmail") == "/integrations?connect=gmail"


def test_a_reconnect_names_the_account_to_sign_back_in() -> None:
    assert integration_connect_path("gmail", "ca_1") == "/integrations?connect=gmail&account=ca_1"


def test_ids_are_query_escaped() -> None:
    assert integration_connect_path("a&b", "c d") == "/integrations?connect=a%26b&account=c+d"
