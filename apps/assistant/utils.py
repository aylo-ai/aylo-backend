import re
import requests 
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException

def static_scrape(url):
    headers = {"user-agent": 
               ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36")}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        parts = soup.find_all("p","h1","span","h2","h3","h4","h5","h6")
        return "\n".join(part.get_text(strip=True) for part in parts if part.get_text(strip=True))
    
    except requests.RequestException as e:
        print(f"Error fetching static content: {e}")
        return ""
    
def dynamic_scrape(url):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    try:
        driver = webdriver.Chrome(options=options)
        driver.get(url)
        driver.implicitly_wait(5)  # wait for JS to load

        elements = driver.find_elements("css selector", "p, h1, h2, li")
        content = "\n".join(el.text for el in elements if el.text.strip())
        driver.quit()
        return content
    
    except WebDriverException as e:
        print(f"Error fetching dynamic content: {e}")
        return ""
    
def check_telegram_link(link):
    telegram_patterns = r"^https://t\.me/[a-zA-Z0-9_]+$"
    return bool(re.match(telegram_patterns, link))

def check_website_link(link):
    website_patterns = r"^(https?://)?(www\.)?[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(/.*)?$"
    return bool(re.match(website_patterns, link))