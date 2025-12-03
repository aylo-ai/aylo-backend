import requests
# import time

# # secret_token = '5a877c65e211f8cf24e0ae4766f59eed98f84c62357fdb2dc626a9f5bbed8b42750ae5aba915089246b707af08871870b4d20e66c934bf3d2b1b1254a3f7a91528a5169ab344534c22cde9e5e64a2f404fcd8e895c357d6cd1951b5daac313aa6fba7fd104a80d08c270cd2ab422ac949047b3edebce24ff'
# # data = requests.post('https://api-admin.billz.ai/v1/auth/login', json={"secret_token": secret_token})
# # data = data.json()
# # print(data)

secret_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjbGllbnRfcGxhdGZvcm1faWQiOiI3ZDRhNGMzOC1kZDg0LTQ5MDItYjc0NC0wNDg4YjgwYTRjMDEiLCJjb21wYW55X2lkIjoiNGY5NjYxOTgtZjA5Yy00YmJlLWEzMWEtYmE2YjAxNjIxY2Q5IiwiZGF0YSI6IiIsImV4cCI6MTc2NDkzNzU0NiwiaWF0IjoxNzYzNjQxNTQ2LCJpZCI6ImExZTVmYjJiLTRlYjEtNDA0Mi04ZjJmLTlmZGUwMWM1MjlhOSIsInVzZXJfaWQiOiI3N2MyMGFkYy03MDk0LTQ5ZjktODk2MS1iMmI0ZjMxNWFmOTAifQ.0YlZ9JsQThwHgYconf-MLZlwA2Lew7l_GCqnUAMsWXk"
filter_data = {
    "company_id": ["4f966198-f09c-4bbe-a31a-ba6b01621cd9"]
}
data = requests.get('https://api-admin.billz.ai/v2/category', headers={"Authorization": f"Bearer {secret_token}", "Content-Type": "application/json"}, params={"limit": 1000})
data = data.json()
print(data)
# 885e207f-47c6-4bde-a6c4-c50bf074b134


# def send_instagram_direct_message(access_token, account_id, sender_id, message):
#     url = f"https://graph.instagram.com/v23.0/{account_id}/messages"
#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {access_token}",
#     }

#     success = True
#     payload = {"recipient": {"id": sender_id}, "message": {"text": message}}

#     response = requests.post(url, json=payload, headers=headers)
#     print(f"[+] Send_instagram_direct_message response: {response.text}")

#     if response.status_code != 200:
#         success = False
#     print(response.json())
#     return success

# print(send_instagram_direct_message("IGAARTl03yXtZABZAFFSSkNiM25BaTQ2ekdDVTFlTUZAkV0xRT1lrX3Rzcl9iVGI2dkRYeksyZA2ZAaVUpHZA3ZANX09ibWlHNUlpVnNjTEtsSWRRbEFCckhiYVFVWm0xN2RVV0RkaFQ4Q3ZAmOHFORy1kUlptNkhR", '17841460285897235', '1490667048879565', 'https://t.me/investorlikqollanmasi'))

# def checking_instagram_followers(access_token:str, recicipient_id:str):
#     url = "https://graph.instagram.com/v23.0/me/media"
#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {access_token}",
#     }
#     params = {
#             "access_token": access_token,
#             "fields": "id,media_type,media_url,username,timestamp,caption,comments_count,like_count,permalink,thumbnail_url,children{media_type,media_url}"
#         }
#     response = requests.get(url, headers=headers, params=params)
#     return response.json()

# print(checking_instagram_followers(recicipient_id="1968400874008971",access_token="IGAARTl03yXtZABZAFF0bUowSHphMnpsczdBbXIxLXlhMmFuS1pIel9vZAUtHUXhNZADRDQkZAYQzRKOUJ6ZATRRd3lPNVE5NU9hVlUzVGJEMFVuNVRtVnhMS04wbHFKN0dBVl9TaEZAVN1dpbXVJWU1FV1JYU293"))
# def fetch_conversation_messages(access_token: str, conversation_id: str):
#     """
#     Fetch full message objects for a single conversation, following pagination.
#     Returns list[dict] of messages: id, from, to, message, created_time, attachments.
#     """
#     messages = []
#     base = f"https://graph.instagram.com/v23.0/{conversation_id}/messages"
#     params = {
#         "fields": "id,from,to,message",
#     }
#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {access_token}",
#     }

#     next_url = base
#     next_params = params

#     while next_url:
#         resp = requests.get(next_url, headers=headers, params=next_params)
#         if resp.status_code != 200:
#             break
#         payload = resp.json() or {}
#         page_items = payload.get("data", [])
#         print(page_items, "page items messages")
#         for item in page_items:
#             if item.get("message") and item.get("message") != "": 
#               messages.append(item.get("message"))

#         paging = payload.get("paging", {})
#         next_url = paging.get("next")
#         next_params = None

#     return messages


# def fetch_all_conversations_with_messages(
#     access_token: str,
# ):
#     """
#     Fetch all conversations (paginated) and, for each, fetch all messages (paginated).
#     Returns list[dict] with keys: id, participants (list[dict]), messages (list[dict]).
#     """
#     collected = []
#     conv_url = "https://graph.instagram.com/v23.0/me/conversations"
#     conv_params = {
#         "fields": "id,participants",
#     }
#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {access_token}",
#     }

#     next_url = conv_url
#     next_params = conv_params

#     while next_url:
#         resp = requests.get(next_url, headers=headers, params=next_params)
#         if resp.status_code != 200:
#             break
#         payload = resp.json() or {}
#         print(payload, "payload coversation")
#         for conv in payload.get("data", []):
#             conv_id = conv.get("id")
#             if not conv_id:
#                 continue
#             msgs = fetch_conversation_messages(
#                 access_token,
#                 conv_id,
#             )
#             if msgs:
#               collected.append({
#                 "messages": msgs,
#             })

#         paging = payload.get("paging", {})
#         next_url = paging.get("next")
#         next_params = None
#     return collected

# response = fetch_all_conversations_with_messages(access_token="IGAARTl03yXtZABZAFBJU2F0TDJfYktBa2hvaW5ZAX2VYZADVjdm1yZAnZAUVEdEWWtGaFRtb1ZAweGUycDZAIR1QwdmVqZAlhoNHVmbWFVd0lxWldHWFB0aHk2b3BMTF9NajBfX2lIVWtpclAtRy1Rb3RXcm1aRktn",
# )

# print(response)
# def send_instagram_postback(account_id: str, access_token:str, recipient_id: str):
#     url = "https://graph.instagram.com/v23.0/17841461784331766/conversations?fields=id,participants,messages%7Bid,from,to,message,created_time,attachments%7D&limit=25&after=ZAXlKMGFXMWxjM1JoYlhBaU9qRTNOVEE1TWpBek5qSXNJblJvY21WaFpBRjlwWkFDSTZAJak0wTURJNE1qTTJOamcwTVRjeE1ETXdNVEkwTkRJM05qSXpNamMyTlRjME5qWXdOamN6TnlKOQZDZD"
#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {access_token}",
#     }
    
#     response = requests.get(url, headers=headers)
#     return response.json()

# response = send_instagram_postback(access_token="IGAARTl03yXtZABZAFBJU2F0TDJfYktBa2hvaW5ZAX2VYZADVjdm1yZAnZAUVEdEWWtGaFRtb1ZAweGUycDZAIR1QwdmVqZAlhoNHVmbWFVd0lxWldHWFB0aHk2b3BMTF9NajBfX2lIVWtpclAtRy1Rb3RXcm1aRktn",
#                         account_id="17841461784331766", recipient_id="1968400874008971")

# print(response)

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

# def get_all_posts(access_token):
#     url = f"https://graph.instagram.com/v23.0/18034220228417379"
#     params = {
#         "access_token": access_token,
#         "fields": "id,media_type,media_url,username,timestamp,caption,comments_count,like_count,permalink,thumbnail_url,children{id,media_type,media_url,username,timestamp,caption,comments_count,like_count,permalink,thumbnail_url}"
#     }
#     response = requests.get(url, params=params)
#     return response.json()
# print(get_all_posts(""))

# def get_comment_from_post(access_token, post_id):
#     url = f"https://graph.instagram.com/v23.0/{post_id}/comments"
#     params = {
#         "access_token": access_token,
#         "fields": "id,text,username,timestamp,from"
#     }
#     response = requests.get(url, params=params)
#     return response.json()
# print(get_comment_from_post(access_token, '17878953921223680'))


# import json



# def test_payoad(assistant_response):
#     try:
#         assistant_response = json.loads(assistant_response)
#         intent = assistant_response.get("intent", None)
#         message = assistant_response.get("reply", None)
#         entities = assistant_response.get("entities", None)
#         if assistant_response.get("properties",None):
#             response_json = assistant_response.get("properties")
#             intent = response_json.get("intent", None)
#             message = response_json.get("reply", None)
#             entities = response_json.get("entities", None)
#     except Exception as e:
#         print(f"Error loading assistant response: {e}")
#         message = assistant_response
#         intent = None
#     return intent, message

# print(test_payoad('Slaom jiagr {name: "John Doe", phone_number: "1234567890", email: "john.doe@example.com"}'))