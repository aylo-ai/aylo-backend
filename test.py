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