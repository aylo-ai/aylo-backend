import uuid
from google.oauth2.service_account import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json
from datetime import datetime
import boto3
from django.core.files.base import ContentFile
from apps.assistant.models import AssistantFileUpload
from apps.shared.addons.enums import FileTypes
from config.settings import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME
import re

def extract_doc_id(url):
    """Extract document ID and type from Google URL."""
    # Patterns for different Google document types
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
    """Format the data into a training-friendly structure."""
    if not rows or len(rows) < 2:  # Need at least header and one data row
        return []
    
    headers = rows[0]
    formatted_data = []
    
    for row in rows[1:]:  # Skip header row
        # Ensure row has same length as headers by padding with empty strings
        row_data = row + [''] * (len(headers) - len(row))
        # Create a dictionary for each row
        row_dict = dict(zip(headers, row_data))
        formatted_data.append(row_dict)
    
    return formatted_data

def upload_to_s3(file_content, filename):
    """Upload file to S3 bucket."""
    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
    
    try:
        s3_client.put_object(
            Bucket=AWS_STORAGE_BUCKET_NAME,
            Key=filename,
            Body=file_content
        )
        return f"https://{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com/{filename}"
    except Exception as e:
        print(f"❌ Error uploading to S3: {e}")
        return None

def get_doc_content(doc_id, assistant):
    """Get content from Google Doc and save as text file."""
    SERVICE_ACCOUNT_FILE = "apps/shared/addons/repli-ai-cred.json"
    SCOPES = ["https://www.googleapis.com/auth/documents.readonly"]
    
    # -------- AUTHENTICATE --------
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build("docs", "v1", credentials=creds)
    
    try:
        # Get document content
        document = service.documents().get(documentId=doc_id).execute()
        
        # Extract text content
        content = []
        for element in document.get('body', {}).get('content', []):
            if 'paragraph' in element:
                for para_element in element['paragraph']['elements']:
                    if 'textRun' in para_element:
                        content.append(para_element['textRun']['content'])
        
        # Join all text content
        text_content = ''.join(content)
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        text_filename = f"document_{timestamp}.txt"
        
        # Upload to S3
        s3_url = upload_to_s3(text_content.encode('utf-8'), text_filename)
        
        if s3_url:
            # Create AssistantFileUpload record
            try:
                file_upload = AssistantFileUpload.objects.create(
                    assistant=assistant,
                    file=ContentFile(text_content.encode('utf-8'), name=text_filename),
                    filename=text_filename,
                    google_sheet_doc_id=doc_id,
                    file_type=FileTypes.GOOGLE_DOCUMENT
                )
                print(f"✅ Document uploaded and record created: {file_upload.filename}")
                
                # Create the Google Doc URL
                doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
                
                return {
                    "status": "success",
                    "message": "Document successfully processed and uploaded",
                    "file_url": s3_url,
                    "file_name": file_upload.filename,
                    "sheet_doc_url": doc_url,
                    "assistant_id": assistant.id,
                    "file_type": FileTypes.GOOGLE_DOCUMENT.value
                }
            except Exception as e:
                print(f"❌ Error creating AssistantFileUpload record: {e}")
                return {
                    "status": "error",
                    "message": f"Error creating record: {str(e)}"
                }
        else:
            return {
                "status": "error",
                "message": "Failed to upload to S3"
            }
            
    except Exception as e:
        print(f"❌ Error processing document: {e}")
        return {
            "status": "error",
            "message": f"Error processing document: {str(e)}"
        }

def get_sheet_data(spreadsheet_id, assistant):
    SERVICE_ACCOUNT_FILE = "apps/shared/addons/repli-ai-cred.json"
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    SPREADSHEET_ID = spreadsheet_id

    # -------- AUTHENTICATE --------
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build("sheets", "v4", credentials=creds)

    # -------- GET SPREADSHEET INFO --------
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    spreadsheet_title = spreadsheet.get('properties', {}).get('title', 'untitled_spreadsheet')
    sheet_titles = [sheet['properties']['title'] for sheet in spreadsheet['sheets']]

    # -------- READ EACH SHEET DYNAMICALLY --------
    all_data = {}
    training_data = []

    for title in sheet_titles:
        try:
            result = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=title
            ).execute()
            rows = result.get("values", [])
            
            # Store raw data
            all_data[title] = rows
            
            # Format data for training
            formatted_data = format_data_for_training(rows)
            if formatted_data:
                training_data.extend(formatted_data)
            
        except Exception as e:
            print(f"❌ Could not read sheet '{title}': {e}")

    if training_data:
        # Create JSON content
        json_content = json.dumps(training_data, ensure_ascii=False, indent=2)
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_filename = f"{spreadsheet_title}_{timestamp}.json"
        
        # Upload to S3
        s3_url = upload_to_s3(json_content.encode('utf-8'), json_filename)
        
        if s3_url:
            # Create AssistantFileUpload record
            try:
                file_upload = AssistantFileUpload.objects.create(
                    assistant=assistant,
                    file=ContentFile(json_content.encode('utf-8'), name=json_filename),
                    filename=json_filename,
                    google_sheet_doc_id=spreadsheet_id,
                    file_type=FileTypes.GOOGLE_SPREADSHEET.value
                )
                print(f"✅ File uploaded and record created: {file_upload.filename}")
                
                # Create the Google Sheets URL
                sheet_doc_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
                
                return {
                    "status": "success",
                    "message": "Data successfully processed and uploaded",
                    "file_url": s3_url,
                    "file_name": file_upload.filename,
                    "sheet_doc_url": sheet_doc_url,
                    "assistant_id": assistant.id,
                    "file_type": FileTypes.GOOGLE_SPREADSHEET
                }
            except Exception as e:
                print(f"❌ Error creating AssistantFileUpload record: {e}")
                return {
                    "status": "error",
                    "message": f"Error creating record: {str(e)}"
                }
    else:
        return {
            "status": "error",
            "message": "No data to process"
        }

def process_google_doc(url, assistant):
    """Process Google Doc URL and determine its type."""
    
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

# Example usage
# url = "https://docs.google.com/document/d/your-doc-id/edit"
# print(process_google_doc(url))
# def watch_google_drive_file(file_id, webhook_url):

#     SCOPES = [
#         'https://www.googleapis.com/auth/drive',
#         'https://www.googleapis.com/auth/drive.file'
#     ]
    
#     try:
#         # Load credentials
#         creds = service_account.Credentials.from_service_account_file(
#             'apps/shared/addons/repli-ai-cred.json',
#             scopes=SCOPES
#         )        # Build the service
#         service = build('drive', 'v3', credentials=creds)
        
#         try:
#             file_info = service.files().get(fileId=file_id).execute()
#             print(f"✅ File accessible: {file_info.get('name', 'Unknown')}")
#         except Exception as e:
#             print(f"❌ Cannot access file {file_id}: {e}")
#             return {
#                 "status": "error",
#                 "message": f"Cannot access file: {str(e)}"
#             }

#         # Watch channel setup
#         channel_id = str(uuid.uuid4())  # Unique per watch
#         channel = {
#             "id": channel_id,
#             "type": "web_hook",
#             "address": webhook_url,
#         }

#         # Set up the watch
#         response = service.files().watch(fileId=file_id, body=channel).execute()
        
#     except Exception as e:
#         print(f"❌ Error setting up watch: {e}")
#         return {
#             "status": "error",
#             "message": f"Error setting up watch: {str(e)}"
#         }

# # Example usage - uncomment to test
# result = watch_google_drive_file(
#     '1_U_QXvZi_z6yXa5PnOH3UCBpGR8g-r4AixTplgTAtkg', 
#     "https://2114-89-249-62-104.ngrok-free.app/api/v1/integration/google-drive/webhook/"
# )
# print(result)
