#!/usr/bin/env python3
"""
Test script for Google Drive API integration
Run this to verify your setup and troubleshoot issues
"""

import sys
import os

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from apps.shared.addons.google_integrations import watch_google_drive_file
from google.oauth2 import service_account
from googleapiclient.discovery import build

def test_service_account():
    """Test if service account can authenticate"""
    try:
        SCOPES = ['https://www.googleapis.com/auth/drive']
        creds = service_account.Credentials.from_service_account_file(
            'apps/shared/addons/repli-ai-cred.json',
            scopes=SCOPES
        )
        
        service = build('drive', 'v3', credentials=creds)
        
        # Test basic API call
        about = service.about().get(fields="user").execute()
        print("✅ Service account authentication successful")
        print(f"📧 Service account email: {about.get('user', {}).get('emailAddress')}")
        return True
        
    except Exception as e:
        print(f"❌ Service account authentication failed: {e}")
        return False

def test_file_access(file_id):
    """Test if we can access the specific file"""
    try:
        SCOPES = ['https://www.googleapis.com/auth/drive']
        creds = service_account.Credentials.from_service_account_file(
            'apps/shared/addons/repli-ai-cred.json',
            scopes=SCOPES
        )
        
        service = build('drive', 'v3', credentials=creds)
        
        # Try to get file info
        file_info = service.files().get(fileId=file_id).execute()
        print(f"✅ File access successful")
        print(f"📄 File name: {file_info.get('name')}")
        print(f"📄 File type: {file_info.get('mimeType')}")
        return True
        
    except Exception as e:
        print(f"❌ File access failed: {e}")
        return False

def test_watch_setup(file_id, webhook_url):
    """Test the watch setup"""
    print(f"\n🔄 Testing watch setup for file: {file_id}")
    print(f"🌐 Webhook URL: {webhook_url}")
    
    result = watch_google_drive_file(file_id, webhook_url)
    
    if result.get("status") == "success":
        print("✅ Watch setup successful!")
        print(f"🔑 Channel ID: {result.get('channel_id')}")
        print(f"🆔 Resource ID: {result.get('resource_id')}")
    else:
        print(f"❌ Watch setup failed: {result.get('message')}")
    
    return result

def main():
    print("🧪 Google Drive API Test Suite")
    print("=" * 50)
    
    # Test file ID (replace with your actual file ID)
    file_id = '1_U_QXvZi_z6yXa5PnOH3UCBpGR8g-r4AixTplgTAtkg'
    webhook_url = "https://2114-89-249-62-104.ngrok-free.app/api/v1/integration/google-drive/webhook/"
    
    # Step 1: Test service account authentication
    print("\n1️⃣ Testing service account authentication...")
    auth_success = test_service_account()
    
    if not auth_success:
        print("\n❌ Authentication failed. Please check:")
        print("   - Google Drive API is enabled in Google Cloud Console")
        print("   - Service account has proper permissions")
        print("   - Credentials file is valid")
        return
    
    # Step 2: Test file access
    print("\n2️⃣ Testing file access...")
    file_access_success = test_file_access(file_id)
    
    if not file_access_success:
        print("\n❌ File access failed. Please check:")
        print("   - File exists and is accessible")
        print("   - Service account has been added to file permissions")
        print("   - File ID is correct")
        return
    
    # Step 3: Test watch setup
    print("\n3️⃣ Testing watch setup...")
    watch_result = test_watch_setup(file_id, webhook_url)
    
    if watch_result.get("status") == "success":
        print("\n🎉 All tests passed! Your Google Drive API setup is working correctly.")
    else:
        print("\n⚠️  Watch setup failed. This might be due to:")
        print("   - Domain verification required for webhooks")
        print("   - Webhook URL not publicly accessible")
        print("   - Consider using polling instead of webhooks")

if __name__ == "__main__":
    main() 