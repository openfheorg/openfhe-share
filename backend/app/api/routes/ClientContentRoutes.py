"""Routes for delivering site-specific SHARE Client content."""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.api.models.ClientContentRequest import ClientStartupKitRequest
from app.core.content_delivery.ClientStartupKitDeliveryService import (
    ClientSiteNotFoundError,
    ClientStartupKitDeliveryError,
    ClientStartupKitDeliveryService,
    InvalidClientNameError,
    InvalidClientSiteError,
)


router = APIRouter()


@router.post(
    "/clients/content/startup-kit",
    response_class=FileResponse,
    responses={
        200: {
            "content": {"application/gzip": {}},
            "description": "Site-specific NVFlare startup-kit archive.",
        },
        400: {"description": "The client site identifier is invalid."},
        404: {"description": "The requested client site folder was not found."},
        409: {"description": "The site folder is not a valid NVFlare startup kit."},
        500: {"description": "The startup kit could not be packaged."},
    },
    summary="Download a client startup kit",
)
def download_client_startup_kit(payload: ClientStartupKitRequest) -> FileResponse:
    """Package the requested client workspace folder and return it as tar.gz bytes."""
    service = ClientStartupKitDeliveryService()

    try:
        artifact = service.create_archive(payload.client_name)
    except InvalidClientNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ClientSiteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidClientSiteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ClientStartupKitDeliveryError as exc:
        logging.exception("Unable to prepare the client startup-kit archive")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logging.exception("Unexpected error while preparing the client startup-kit archive")
        raise HTTPException(
            status_code=500,
            detail="The startup kit could not be packaged",
        ) from exc

    return FileResponse(
        path=artifact.path,
        media_type="application/gzip",
        filename=artifact.download_filename,
        headers={
            "X-SHARE-Client-Site": payload.client_name.strip(),
            "X-SHARE-Artifact-SHA256": artifact.sha256,
            "X-SHARE-Artifact-Size": str(artifact.size_bytes),
        },
        background=BackgroundTask(artifact.cleanup),
    )
