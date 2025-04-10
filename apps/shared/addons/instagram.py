import requests


def get_instagram_business_accounts(access_token):
    """Fetch Instagram Business Accounts connected to the user's Facebook pages"""
    url = f"https://graph.facebook.com/v22.0/me/accounts?access_token={access_token}"
    response = requests.get(url)
    print(f"response text: {response.text}")
    if response.status_code == 200:
        print(f"Response: {response.json()}")
        accounts = response.json().get("data", [])
        business_accounts = []
        for account in accounts:
            if "instagram_business_account" in account:
                business_accounts.append({
                    "page_id": account["id"],
                    "page_name": account["name"],
                    "instagram_id": account["instagram_business_account"]["id"]
                })
        return business_accounts
    return None


def get_long_lived_access_token(short_lived_access_token):
    """Get long-lived access token from short-lived access token"""
    CLIENT_SECRET = "5012f3e33700b8b659a9c97c1fc1f7bd"
    grant_type = "ig_exchange_token"
    url = f"https://graph.instagram.com/access_token?grant_type={grant_type}&" \
          f"client_secret={CLIENT_SECRET}&access_token={short_lived_access_token}"

    response = requests.get(url)
    if response.status_code == 200:
        access_token = response.json().get("access_token")
        return access_token
    return None


def instagram_refresh_token(access_token):
    grant_type = "ig_refresh_token"
    url = f"https://graph.instagram.com/refresh_access_token?grant_type={grant_type}&access_token={access_token}"

    response = requests.get(url)

