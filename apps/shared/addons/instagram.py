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