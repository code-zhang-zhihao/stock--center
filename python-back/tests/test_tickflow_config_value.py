from types import SimpleNamespace

import pytest

from app.modules.config_center.service import ConfigCenterService


def _config(config_code: str):
    return SimpleNamespace(category_code="market_data", config_code=config_code)


def test_tickflow_api_key_accepts_endpoint_override():
    ConfigCenterService._validate_endpoint_url(_config("tickflow"), "api_key", "https://tickflow.example.test/v1")


def test_tickflow_non_api_key_rejects_endpoint_override():
    with pytest.raises(ValueError, match="endpoint_url"):
        ConfigCenterService._validate_endpoint_url(_config("tickflow"), "token", "https://tickflow.example.test/v1")
