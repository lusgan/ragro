import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

MCR_PDF_PATH = "data/MCR.pdf"
MCR_MD_PATH = "data/MCR_adobe.md"

AUTH_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
API_BASE = "https://pdf-services.adobe.io"

logger = logging.getLogger(__name__)


def _get_token(client_id: str, client_secret: str) -> str:
    resp = requests.post(
        AUTH_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "openid,AdobeID,DCAPI",
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _upload_pdf(pdf_path: str, token: str, client_id: str) -> str:
    headers = {"Authorization": f"Bearer {token}", "X-API-Key": client_id}

    # Request upload URI
    resp = requests.post(
        f"{API_BASE}/assets",
        headers={**headers, "Content-Type": "application/json"},
        json={"mediaType": "application/pdf"},
    )
    resp.raise_for_status()
    data = resp.json()
    upload_uri = data["uploadUri"]
    asset_id = data["assetID"]

    # Upload PDF bytes
    with open(pdf_path, "rb") as f:
        put_resp = requests.put(
            upload_uri,
            headers={"Content-Type": "application/pdf"},
            data=f,
        )
    put_resp.raise_for_status()

    return asset_id


def _submit_job(asset_id: str, token: str, client_id: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-API-Key": client_id,
        "Content-Type": "application/json",
    }
    resp = requests.post(
        f"{API_BASE}/operation/pdftomarkdown",
        headers=headers,
        json={"assetID": asset_id, "getFigures": False},
    )
    resp.raise_for_status()
    return resp.headers["Location"]


def _poll_job(location: str, token: str, client_id: str) -> str:
    headers = {"Authorization": f"Bearer {token}", "X-API-Key": client_id}
    while True:
        resp = requests.get(location, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        status = body["status"]
        if status == "done":
            return body["asset"]["downloadUri"]
        if status == "failed":
            raise RuntimeError(f"Adobe job failed: {body}")
        time.sleep(3)


def extract(pdf_path: str = MCR_PDF_PATH, md_path: str = MCR_MD_PATH) -> str:
    out = Path(md_path)
    if out.exists():
        logger.info("Output already exists, skipping extraction: %s", md_path)
        return md_path

    load_dotenv()
    client_id = os.environ["ADOBE_CLIENT_ID"]
    client_secret = os.environ["ADOBE_CLIENT_SECRET"]

    token = _get_token(client_id, client_secret)
    asset_id = _upload_pdf(pdf_path, token, client_id)
    location = _submit_job(asset_id, token, client_id)
    download_uri = _poll_job(location, token, client_id)

    content = requests.get(download_uri)
    content.raise_for_status()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content.content)

    logger.info("Extraction complete: %s", md_path)
    return md_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    extract()
