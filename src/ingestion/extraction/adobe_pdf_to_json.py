"""Adobe PDF Extract API — extrai conteúdo estruturado do PDF em JSON.

Retorna um ZIP com structuredData.json contendo elementos tipados
(H1, P, Header, Footer, Table, etc.) com número de página e bounding box.
"""

import json
import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

MCR_PDF_PATH  = "data/MCR.pdf"
MCR_JSON_PATH = "data/MCR_adobe.json"

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
    resp = requests.post(
        f"{API_BASE}/assets",
        headers={**headers, "Content-Type": "application/json"},
        json={"mediaType": "application/pdf"},
    )
    resp.raise_for_status()
    data = resp.json()
    with open(pdf_path, "rb") as f:
        requests.put(
            data["uploadUri"],
            headers={"Content-Type": "application/pdf"},
            data=f,
        ).raise_for_status()
    return data["assetID"]


def _submit_job(asset_id: str, token: str, client_id: str) -> str:
    resp = requests.post(
        f"{API_BASE}/operation/extractpdf",
        headers={
            "Authorization": f"Bearer {token}",
            "X-API-Key": client_id,
            "Content-Type": "application/json",
        },
        json={
            "assetID": asset_id,
            "elementsToExtract": ["text", "tables"],
            "includeHeaderFooter": True,
            "tableOutputFormat": "csv",
        },
    )
    resp.raise_for_status()
    return resp.headers["Location"]


def _poll(location: str, token: str, client_id: str) -> str:
    headers = {"Authorization": f"Bearer {token}", "X-API-Key": client_id}
    while True:
        resp = requests.get(location, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        status = body["status"]
        logger.info("Status: %s", status)
        if status == "done":
            # 'content' = JSON direto (structuredData); 'resource' = ZIP com CSVs
            # Retorna (json_uri, zip_uri)
            return body["content"]["downloadUri"], body.get("resource", {}).get("downloadUri")
        if status == "failed":
            raise RuntimeError(f"Adobe Extract job falhou: {body}")
        time.sleep(3)


def extract(pdf_path: str = MCR_PDF_PATH, json_path: str = MCR_JSON_PATH) -> str:
    """Extrai MCR.pdf via Adobe Extract PDF e salva structuredData.json.

    Returns:
        Caminho para o JSON gerado.
    """
    out = Path(json_path)
    if out.exists():
        logger.info("JSON ja existe, pulando extracao: %s", json_path)
        return json_path

    load_dotenv()
    client_id     = os.environ["ADOBE_CLIENT_ID"]
    client_secret = os.environ["ADOBE_CLIENT_SECRET"]

    logger.info("Autenticando...")
    token = _get_token(client_id, client_secret)

    logger.info("Enviando PDF: %s", pdf_path)
    asset_id = _upload_pdf(pdf_path, token, client_id)

    logger.info("Submetendo job de extracao...")
    location = _submit_job(asset_id, token, client_id)

    logger.info("Aguardando conclusao do job...")
    json_uri, _zip_uri = _poll(location, token, client_id)

    # content.downloadUri aponta direto para o JSON (nao é um ZIP)
    logger.info("Baixando structuredData.json (%.1f MB esperado)...", 24.0)
    resp = requests.get(json_uri)
    resp.raise_for_status()
    data = resp.json()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("Extraidos %d elementos -> %s", len(data.get("elements", [])), json_path)
    return json_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = extract()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    elements = data.get("elements", [])
    print(f"\nTotal de elementos: {len(elements)}\n")
    # Primeiros 10 elementos
    for el in elements[:10]:
        print(json.dumps(el, ensure_ascii=False, indent=2))
