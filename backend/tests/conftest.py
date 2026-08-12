"""pytest 共享夹具。"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    """提供 FastAPI TestClient 实例。"""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
