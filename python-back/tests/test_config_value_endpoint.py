from app.modules.config_center.schemas import ConfigValueCreate, ConfigValueUpdate


def test_endpoint_url_accepts_http_and_normalizes_trailing_slash() -> None:
    payload = ConfigValueCreate(value_name="tushare", value_kind="token", secret="value", endpoint_url=" https://api.example.test/v1/ ")
    assert payload.endpoint_url == "https://api.example.test/v1"


def test_endpoint_url_rejects_non_http_url() -> None:
    try:
        ConfigValueUpdate(endpoint_url="ftp://api.example.test")
    except ValueError as exc:
        assert "endpoint_url" in str(exc)
    else:
        raise AssertionError("endpoint_url must reject non-http schemes")
