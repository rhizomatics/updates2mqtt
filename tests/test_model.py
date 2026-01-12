from updates2mqtt.model import Discovery, ReleaseProvider


def test_discovery_stringifies(mock_provider: ReleaseProvider) -> None:
    uut = Discovery(mock_provider, "test", "test_session", "tester")
    assert str(uut)
