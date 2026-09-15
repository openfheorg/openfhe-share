from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from app.api.models.ClientContentRequest import ClientStartupKitRequest
from app.api.routes.ClientContentRoutes import download_client_startup_kit
from app.core.content_delivery.ClientStartupKitDeliveryService import (
    ClientSiteNotFoundError,
    ClientStartupKitArtifact,
    ClientStartupKitDeliveryError,
    InvalidClientNameError,
    InvalidClientSiteError,
)


def _artifact(tmp_path: Path):
    path = tmp_path / "kit.tar.gz"
    path.write_bytes(b"archive")
    return ClientStartupKitArtifact(
        path=path,
        download_filename="site4.tar.gz",
        sha256="abc123",
        size_bytes=7,
    )


def test_download_route_returns_file_response_and_headers(tmp_path):
    artifact = _artifact(tmp_path)
    with patch(
        "app.api.routes.ClientContentRoutes.ClientStartupKitDeliveryService"
    ) as service_cls:
        service_cls.return_value.create_archive.return_value = artifact
        response = download_client_startup_kit(ClientStartupKitRequest(client_name=" site4 "))

    assert Path(response.path) == artifact.path
    assert response.media_type == "application/gzip"
    assert response.headers["x-share-client-site"] == "site4"
    assert response.headers["x-share-artifact-sha256"] == "abc123"
    assert response.headers["x-share-artifact-size"] == "7"


@pytest.mark.parametrize(
    "error,status",
    [
        (InvalidClientNameError("bad"), 400),
        (ClientSiteNotFoundError("missing"), 404),
        (InvalidClientSiteError("invalid"), 409),
        (ClientStartupKitDeliveryError("failed"), 500),
    ],
)
def test_download_route_maps_known_errors(error, status):
    with patch(
        "app.api.routes.ClientContentRoutes.ClientStartupKitDeliveryService"
    ) as service_cls:
        service_cls.return_value.create_archive.side_effect = error
        with pytest.raises(HTTPException) as exc:
            download_client_startup_kit(ClientStartupKitRequest(client_name="site4"))
    assert exc.value.status_code == status


def test_download_route_hides_unexpected_exception_detail():
    with patch(
        "app.api.routes.ClientContentRoutes.ClientStartupKitDeliveryService"
    ) as service_cls:
        service_cls.return_value.create_archive.side_effect = RuntimeError("filesystem secret")
        with pytest.raises(HTTPException) as exc:
            download_client_startup_kit(ClientStartupKitRequest(client_name="site4"))
    assert exc.value.status_code == 500
    assert exc.value.detail == "The startup kit could not be packaged"
