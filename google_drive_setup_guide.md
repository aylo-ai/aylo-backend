# Google Drive API Setup Guide

## Error: "Method doesn't allow unregistered callers"

This error occurs when the Google Drive API isn't properly configured. Here's how to fix it:

## 1. Enable Google Drive API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project: `repli-ai`
3. Go to **APIs & Services** > **Library**
4. Search for "Google Drive API"
5. Click on it and press **Enable**

## 2. Verify Service Account Permissions

Your service account (`repli-ai@repli-ai.iam.gserviceaccount.com`) needs these roles:

1. Go to **IAM & Admin** > **IAM**
2. Find your service account
3. Add these roles:
   - **Drive API** > **Drive File Stream API**
   - **Drive API** > **Google Drive API**

## 3. File Access Permissions

The service account needs access to the specific file:

1. Open your Google Drive file
2. Click **Share**
3. Add: `repli-ai@repli-ai.iam.gserviceaccount.com`
4. Give it **Editor** or **Viewer** permissions

## 4. Domain Verification (for Webhooks)

If using webhooks, you need to verify your domain:

1. Go to **APIs & Services** > **Domain verification**
2. Add your domain (e.g., `yourdomain.com`)
3. Follow the verification steps

## 5. Test the Setup

Run this test script to verify everything works:

```python
# test_google_drive.py
from apps.shared.addons.google_integrations import watch_google_drive_file

# Test with your file ID
file_id = '1_U_QXvZi_z6yXa5PnOH3UCBpGR8g-r4AixTplgTAtkg'
webhook_url = "https://your-domain.com/api/v1/integration/google-drive/webhook/"

result = watch_google_drive_file(file_id, webhook_url)
print(result)
```

## 6. Alternative: Use Polling Instead of Webhooks

If webhooks continue to cause issues, consider using polling:

```python
def check_file_changes(file_id):
    """Poll for file changes instead of using webhooks"""
    # Implementation here
    pass
```

## Common Issues and Solutions

### Issue 1: "API not enabled"
- **Solution**: Enable Google Drive API in Google Cloud Console

### Issue 2: "Permission denied"
- **Solution**: Add service account to file permissions

### Issue 3: "Domain not verified"
- **Solution**: Verify your domain or use polling instead

### Issue 4: "Invalid webhook URL"
- **Solution**: Ensure URL is HTTPS and publicly accessible

## Next Steps

1. Enable the Google Drive API
2. Add service account to file permissions
3. Test with the updated function
4. If webhooks fail, consider implementing polling 