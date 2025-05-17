from playwright.sync_api import sync_playwright
import os
import time
from datetime import datetime
import img2pdf
import logging
import random

class WebsiteScreenshot:
    def __init__(self, output_dir="parsing"):
        self.output_dir = output_dir
        self.setup_logging()
        self.create_output_directory()
        
        # List of common user agents
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15'
        ]
        
    def setup_logging(self):
        """Configure logging for the class"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
    def create_output_directory(self):
        """Create output directory if it doesn't exist"""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            self.logger.info(f"Created output directory: {self.output_dir}")
            
    def get_random_user_agent(self):
        """Get a random user agent from the list"""
        return random.choice(self.user_agents)
            
    def capture_full_page(self, url):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = os.path.join(self.output_dir, f"screenshot_{timestamp}.png")
        
        try:
            with sync_playwright() as p:
                # Launch browser with anti-detection measures
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--disable-site-isolation-trials'
                    ]
                )
                
                # Create context with custom settings
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent=self.get_random_user_agent(),
                    locale='en-US',
                    timezone_id='America/New_York',
                    geolocation={'latitude': 40.7128, 'longitude': -74.0060},
                    permissions=['geolocation'],
                    color_scheme='light',
                    device_scale_factor=1,
                    is_mobile=False,
                    has_touch=False,
                    java_script_enabled=True,
                    extra_http_headers={
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Sec-Fetch-User': '?1',
                        'DNT': '1'
                    }
                )
                
                # Add custom scripts to bypass detection
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });
                """)
                
                page = context.new_page()
                
                # Add random delay before navigation
                time.sleep(random.uniform(1, 3))
                
                # Navigate to URL with retry mechanism
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        self.logger.info(f"Navigating to: {url} (Attempt {attempt + 1}/{max_retries})")
                        response = page.goto(
                            url,
                            wait_until="networkidle",
                            timeout=30000
                        )
                        
                        if response.status == 403 or response.status == 429:
                            self.logger.warning(f"Access denied (Status {response.status}). Retrying...")
                            time.sleep(random.uniform(5, 10))  # Longer delay for blocked requests
                            continue
                            
                        break
                    except Exception as e:
                        if attempt == max_retries - 1:
                            raise
                        self.logger.warning(f"Navigation failed: {str(e)}. Retrying...")
                        time.sleep(random.uniform(2, 5))
                
                # Simulate human-like behavior
                page.mouse.move(
                    random.randint(0, 1920),
                    random.randint(0, 1080)
                )
                page.mouse.wheel(delta_x=0, delta_y=random.randint(100, 300))
                time.sleep(random.uniform(1, 2))
                
                # Wait for any dynamic content to load
                time.sleep(random.uniform(2, 4))
                
                # Get page dimensions
                dimensions = page.evaluate("""() => {
                    return {
                        width: Math.max(document.documentElement.clientWidth, document.body.scrollWidth),
                        height: Math.max(document.documentElement.clientHeight, document.body.scrollHeight)
                    }
                }""")
                
                # Set viewport size to full page dimensions
                page.set_viewport_size({
                    "width": dimensions["width"],
                    "height": dimensions["height"]
                })
                
                # Take screenshot
                self.logger.info("Capturing full-page screenshot...")
                page.screenshot(path=screenshot_path, full_page=True)
                
                browser.close()
                self.logger.info(f"Screenshot saved to: {screenshot_path}")
                return screenshot_path
                
        except Exception as e:
            self.logger.error(f"Error capturing screenshot: {str(e)}")
            raise
            
    def convert_to_pdf(self, image_path):
        try:
            pdf_path = image_path.replace('.png', '.pdf')
            
            # Convert image to PDF
            self.logger.info("Converting screenshot to PDF...")
            with open(pdf_path, "wb") as f:
                f.write(img2pdf.convert(image_path))
                
            self.logger.info(f"PDF saved to: {pdf_path}")
            return pdf_path
            
        except Exception as e:
            self.logger.error(f"Error converting to PDF: {str(e)}")
            raise
            
    def process_url(self, url):
        try:
            screenshot_path = self.capture_full_page(url)
            pdf_path = self.convert_to_pdf(screenshot_path)
            return screenshot_path, pdf_path
            
        except Exception as e:
            self.logger.error(f"Error processing URL: {str(e)}")
            raise
