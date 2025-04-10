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
          f"fields=id,username,profile_picture_url,followers_count,follows_count,account_type&" \
          f"access_token={access_token}"
    response = requests.get(url)
    print(f"get_user_profile response: {response.text}")
    if response.status_code == 200:
        user_profile = response.json()
        # user_data = {
        #     "id": user_profile.get("data")[0].get("user_id"),
        #     "username": user_profile.get("data")[0].get("username"),
        #     "profile_picture": user_profile.get("data")[0].get("profile_picture_url"),
        #     "followers_count": user_profile.get("data")[0].get("followers_count"),
        #     "follows_count": user_profile.get("data")[0].get("follows_count"),
        #     "account_type": user_profile.get("data")[0].get("account_type"),
        # }
        return user_profile
    return None
