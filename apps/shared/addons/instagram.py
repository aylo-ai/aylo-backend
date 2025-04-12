import requests


def get_long_lived_access_token(short_lived_access_token):
    """Get long-lived access token from short-lived access token"""
    CLIENT_SECRET = "dc12159193e69625fd27281997b28f4f"
    grant_type = "ig_exchange_token"
    url = f"https://graph.instagram.com/access_token?grant_type={grant_type}&" \
          f"client_secret={CLIENT_SECRET}&access_token={short_lived_access_token}"

    response = requests.get(url)
    if response.status_code == 200:
        access_token = response.json().get("access_token")
        refreshed_new_token = instagram_refresh_token(access_token)
        print(f"refresh_token: {refreshed_new_token}")
        return access_token
    return None


def instagram_refresh_token(access_token):
    grant_type = "ig_refresh_token"
    url = f"https://graph.instagram.com/refresh_access_token?grant_type={grant_type}&access_token={access_token}"

    response = requests.get(url)
    if response.status_code == 200:
        access_token = response.json().get("access_token")
        return access_token
    return None


def get_user_profile(access_token):
    """Get user profile from access token"""
    url = f"https://graph.instagram.com/me?" \
          f"fields=id,user_id,username&" \
          f"access_token={access_token}"
    response = requests.get(url)
    print(f"get_user_profile response: {response.text}")
    if response.status_code == 200:
        user_profile = response.json()
        user_data = {
            "instagram_user_id": user_profile.get("id"),
            "instagram_account_id": user_profile.get("user_id"),
            "instagram_username": user_profile.get("username"),
        }
        return user_data
    return None


def send_instagram_message(account_id, access_token, recipient_id, message):
    """Send message to Instagram user"""
    url = f"https://graph.instagram.com/v22.0/{account_id}/messages"
    header = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    payload = {
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "text": message
        }
    }
    response = requests.post(url, json=payload, headers=header)
    print(f"send_instagram_message response: {response.text}")
    if response.status_code == 200:
        return True
    return False