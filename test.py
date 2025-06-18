import requests

# def get_media_id_from_comment(access_token, comment_id):
#     """Get media (post) ID from a comment"""
#     url = f"https://graph.facebook.com/v23.0/{comment_id}"
#     params = {
#         "fields": "id,text,username,timestamp,media",
#         "access_token": access_token
#     }
#     response = requests.get(url, params=params)
#     print("Comment Details:", response.json())
#     if response.status_code == 200:
#         return response.json().get("media", {}).get("id")
#     return None

# def get_post_details(access_token, media_id):
#     """Get post details using media ID"""
#     url = f"https://graph.instagram.com/v23.0/{media_id}/"
#     params = {
#         "fields": "id,text,username,timestamp,media,from",
#         "access_token": access_token
#     }
#     response = requests.get(url, params=params)
#     print("Post Details:", response.json())
#     return response.json()

# def get_media_comments(access_token, media_id):
#     """Get all comments for a media post using media ID"""
#     url = f"https://graph.instagram.com/v23.0/{media_id}/comments"
#     params = {
#         "fields": "id,text,username,timestamp,from",
#         "access_token": access_token  # Pass token as query parameter instead of header
#     }
#     try:
#         response = requests.get(url, params=params)
#         response.raise_for_status()  # Raise exception for bad status codes
#         print("Media Comments:", response.json())
#         return response.json()
#     except requests.exceptions.RequestException as e:
#         print(f"Error fetching comments: {str(e)}")
#         if response.status_code == 401:
#             print("Authentication failed. Please check your access token.")
#         return None

# # 🔐 Your access token and the comment_id you're interested in
# access_token = "IGAARTl03yXtZABZAFB1RWNoWUdnOTI4SU9lTnNDY2tfTGRsajFlZAjlzX2NqWGJyME9pUVhwWG1nbnJsVEZApSUlicXA4WkF1ZAEMtb016cjVzbC1wLXNOX29ZAMmVJV2ZAaclBfd181cDZAES2RoZAWhaZAmNYTGVB"
# comment_id = "18183087160316336"  # Replace with actual comment ID

# Step 1: Get the media ID from the comment
# media_id = get_media_id_from_comment(access_token, comment_id)

# # Step 2: Get post details from the media ID
# if media_id:
#     post_details = get_post_details(access_token, media_id)
# else:
#     print("Failed to retrieve media ID from comment.")

# print(get_media_comments(access_token, '17878953921223680'))


# def send_private_reply(access_token, account_id, comment_id):
#     """Send a private reply to a comment"""
#     url = f"https://graph.instagram.com/v23.0/{account_id}/messages"
#     params = {
#         "access_token": access_token  # Pass token as query parameter
#     }
#     headers = {
#         "Content-Type": "application/json"
#     }

#     payload = {
#         "recipient": { 
#             "comment_id": comment_id 
#         },
#         "message": { 
#             "text": "What is up this is test and done by automation by repli ai" 
#         }
#     }
#     try:
#         response = requests.post(url, json=payload, headers=headers, params=params)
#         response.raise_for_status()
#         print("Private Reply:", response.json())
#         return response.json()
#     except requests.exceptions.RequestException as e:
#         print(f"Error sending private reply: {str(e)}")
#         if response.status_code == 401:
#             print("Authentication failed. Please check your access token.")
#         return None

# print(send_private_reply(access_token, '17841461784331766', '18065775380087646'))


# def send_reply_to_comment(access_token, comment_id):
#     """Send a reply to a comment"""
#     url = f"https://graph.instagram.com/v23.0/{comment_id}/replies"
#     params = {
#         "access_token": access_token  # Pass token as query parameter
#     }
#     headers = { 
#         "Content-Type": "application/json"
#     }
#     payload = {
#         "message": "this is test bro"
#     }
#     try:
#         response = requests.post(url, json=payload, headers=headers, params=params)
#         response.raise_for_status()
#         print("Reply to Comment:", response.json())
#         return response.json()
#     except requests.exceptions.RequestException as e:
#         print(f"Error sending reply: {str(e)}")
#         if response.status_code == 401:
#             print("Authentication failed. Please check your access token.")
#         return None

# # Test the functions with error handling
# try:
#     # First verify the token is valid
#     verify_url = "https://graph.instagram.com/me"
#     verify_params = {"access_token": access_token}
#     verify_response = requests.get(verify_url, params=verify_params)
#     verify_response.raise_for_status()
#     print("Token is valid!")
    
#     # If token is valid, proceed with your test
#     print(send_reply_to_comment(access_token, "18065775380087646"))
# except requests.exceptions.RequestException as e:
#     print(f"Token verification failed: {str(e)}")
#     if verify_response.status_code == 401:
#         print("Your access token is invalid or expired. Please get a new token.")



import requests

BITRIX_WEBHOOK_URL = "https://b24-l1optd.bitrix24.ru/rest/1/p494qa3urpwurnq7/"  # Replace with your real webhook

def create_bitrix_lead(name='shahid', last_name='khan', phone='9876543210', email='shahid@gmail.com', title="New Lead from My App"):
    url = f"{BITRIX_WEBHOOK_URL}/crm.lead.add.json"
    payload = {
        "fields": {
            "TITLE": title,
            "NAME": name,
            "LAST_NAME": last_name,
            "PHONE": [{"VALUE": phone, "VALUE_TYPE": "WORK"}],
            "EMAIL": [{"VALUE": email, "VALUE_TYPE": "WORK"}],
        }
    }

    response = requests.post(url, json=payload)
    return response.json()

# print(create_bitrix_lead())

def create_bitrix_deal(title, amount=0, stage_id="NEW", contact_id=None):
    url = f"{BITRIX_WEBHOOK_URL}/crm.deal.add.json"

    fields = {
        "TITLE": title,
        "STAGE_ID": stage_id,     # default stage like "NEW" or custom (e.g. PREPAYMENT_INVOICE)
        "OPPORTUNITY": amount     # this is the price or expected amount
    }

    if contact_id:
        fields["CONTACT_ID"] = contact_id

    payload = {
        "fields": fields
    }

    response = requests.post(url, json=payload)
    return response.json()
# print(create_bitrix_deal(title="New Deal from My App", amount=1000))