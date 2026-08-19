import json
import logging
import re
from datetime import datetime

from django.conf import settings
from django.core.files.base import ContentFile
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from apps.assistant.models import AssistantFileUpload
from apps.shared.addons.enums import FileTypes

logger = logging.getLogger(__name__)


def _load_credentials(scopes):
    path = settings.GOOGLE_SERVICE_ACCOUNT_FILE
    try:
        return Credentials.from_service_account_file(path, scopes=scopes)
    except (OSError, ValueError):
        logger.exception(
            "Could not load Google service-account credentials from %s", path
        )
        return None

def extract_doc_id(url):
    patterns = {
        'spreadsheet': r'/spreadsheets/d/([a-zA-Z0-9-_]+)',
        'document': r'/document/d/([a-zA-Z0-9-_]+)',
        'presentation': r'/presentation/d/([a-zA-Z0-9-_]+)',
        'form': r'/forms/d/([a-zA-Z0-9-_]+)'
    }

    for doc_type, pattern in patterns.items():
        match = re.search(pattern, url)
        if match:
            return {
                'id': match.group(1),
                'type': doc_type
            }
    return None

def format_data_for_training(rows):
    if not rows or len(rows) < 2:
        return []

    headers = rows[0]
    formatted_data = []

    for row in rows[1:]:
        row_data = row + [''] * (len(headers) - len(row))
        row_dict = dict(zip(headers, row_data))
        formatted_data.append(row_dict)

    return formatted_data

def get_doc_content(doc_id, assistant):
    creds = _load_credentials(["https://www.googleapis.com/auth/documents.readonly"])
    if creds is None:
        return {
            "status": "error",
            "message": "Google credentials are not configured",
        }
    service = build("docs", "v1", credentials=creds)

    try:
        document = service.documents().get(documentId=doc_id).execute()

        content = []
        for element in document.get('body', {}).get('content', []):
            if 'paragraph' in element:
                for para_element in element['paragraph']['elements']:
                    if 'textRun' in para_element:
                        content.append(para_element['textRun']['content'])

        text_content = ''.join(content)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        text_filename = f"document_{timestamp}.txt"

        try:
            file_upload = AssistantFileUpload.objects.create(
                assistant=assistant,
                file=ContentFile(text_content.encode('utf-8'), name=text_filename),
                filename=text_filename,
                google_sheet_doc_id=doc_id,
                file_type=FileTypes.GOOGLE_DOCUMENT
            )
            logger.info("Stored Google Doc %s as %s", doc_id, file_upload.filename)

            return {
                "status": "success",
                "message": "Document successfully processed and uploaded",
                "file_url": file_upload.file.url,
                "file_name": file_upload.filename,
                "sheet_doc_url": f"https://docs.google.com/document/d/{doc_id}/edit",
                "assistant_id": assistant.id,
                "file_type": FileTypes.GOOGLE_DOCUMENT.value
            }
        except Exception as exc:
            logger.exception("Could not store Google Doc %s", doc_id)
            return {
                "status": "error",
                "message": f"Error creating record: {exc}"
            }

    except Exception as e:
        logger.exception("Error processing Google Doc %s", doc_id)
        return {
            "status": "error",
            "message": f"Error processing document: {str(e)}"
        }

def get_sheet_data(spreadsheet_id, assistant):
    SPREADSHEET_ID = spreadsheet_id

    creds = _load_credentials(["https://www.googleapis.com/auth/spreadsheets.readonly"])
    if creds is None:
        return {
            "status": "error",
            "message": "Google credentials are not configured",
        }
    service = build("sheets", "v4", credentials=creds)

    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    spreadsheet_title = spreadsheet.get('properties', {}).get('title', 'untitled_spreadsheet')
    sheet_titles = [sheet['properties']['title'] for sheet in spreadsheet['sheets']]

    all_data = {}
    training_data = []

    for title in sheet_titles:
        try:
            result = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=title
            ).execute()
            rows = result.get("values", [])

            all_data[title] = rows

            formatted_data = format_data_for_training(rows)
            if formatted_data:
                training_data.extend(formatted_data)

        except Exception:
            logger.warning("Could not read sheet %r", title, exc_info=True)

    if training_data:
        json_content = json.dumps(training_data, ensure_ascii=False, indent=2)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_filename = f"{spreadsheet_title}_{timestamp}.json"

        try:
            file_upload = AssistantFileUpload.objects.create(
                assistant=assistant,
                file=ContentFile(json_content.encode('utf-8'), name=json_filename),
                filename=json_filename,
                google_sheet_doc_id=spreadsheet_id,
                file_type=FileTypes.GOOGLE_SPREADSHEET.value
            )
            logger.info(
                "Stored Google Sheet %s as %s", spreadsheet_id, file_upload.filename
            )

            return {
                "status": "success",
                "message": "Data successfully processed and uploaded",
                "file_url": file_upload.file.url,
                "file_name": file_upload.filename,
                "sheet_doc_url": (
                    f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
                ),
                "assistant_id": assistant.id,
                "file_type": FileTypes.GOOGLE_SPREADSHEET.value
            }
        except Exception as exc:
            logger.exception("Could not store Google Sheet %s", spreadsheet_id)
            return {
                "status": "error",
                "message": f"Error creating record: {exc}"
            }
    else:
        return {
            "status": "error",
            "message": "No data to process"
        }

def process_google_doc(url, assistant):
    doc_info = extract_doc_id(url)
    if doc_info['type'] == 'spreadsheet':
        result = get_sheet_data(doc_info['id'], assistant)
    elif doc_info['type'] == 'document':
        result = get_doc_content(doc_info['id'], assistant)
    else:
        return {
            "sheet_doc_url": url,
            "assistant_id": assistant.id
        }

    if result and result.get("status") == "success":
        return {
            "sheet_doc_url": result.get("sheet_doc_url"),
            "assistant_id": result.get("assistant_id"),
            "file_type": result.get("file_type")
        }
    else:
        return {
            "sheet_doc_url": url,
            "assistant_id": assistant.id,
            "file_type": None
        }
