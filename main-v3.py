#!/usr/bin/env python3
"""
Hybrid Web Scraper CLI Tool
Combines async requests with Selenium session management using real Chrome profiles
Handles human verification blocks with interactive fallback
"""

import asyncio
import aiohttp
import argparse
import random
import re
import os
import sys
import json
import pickle
import time
from pathlib import Path
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException
from urllib.parse import urlparse, urljoin
from datetime import datetime


class HybridWebScraper:
    def __init__(self, input_file='list', output_file='result', concurrency=5, total_requests=1000, 
                 profile_dir='chrome_profile', profile_name='Default', use_selenium=False, 
                 interactive_mode=False, session_file='session_data.json', cookie_file='cookies.pkl'):
        self.input_file = Path(input_file)
        self.output_file = Path(output_file)
        self.concurrency = concurrency
        self.total_requests = total_requests
        self.tries = 0
        self.urls = []

        # Add current_url attribute
        self.current_url = None
        
        # Selenium settings
        self.profile_dir = os.path.abspath(profile_dir)
        self.profile_name = profile_name
        self.use_selenium = use_selenium
        self.interactive_mode = interactive_mode
        self.driver = None
        
        # Session management
        self.session_file = session_file
        self.cookie_file = cookie_file
        self.session_cookies = {}
        self.session_headers = {}
        
        # Verification handling
        self.verification_keywords = [
            'human verification', 'captcha', 'verify you are human', 
            'cloudflare', 'protection', 'checking your browser',
            'please verify', 'security check', 'robot', 'bot'
        ]
    
        # Add verification indicators
        self.just_moment_indicators = [
            'just a moment...',
            'checking if the site connection is secure',
            'checking your browser',
            'please wait while we verify your browser',
            'please enable js and disable any ad blocker',
            'waiting for verification',
            'ddos protection by cloudflare',
            'ray id:',
            'performing additional checks'
        ]
        
        self.unwanted_indicators = [
            'access denied',
            'forbidden',
            'ip has been blocked',
            'too many requests',
            'rate limited',
            'proxy detected',
            'vpn detected',
            'automated access detected',
            'please prove you are human'
        ]
    
    def check_profile_exists(self):
        """Check if Chrome profile directory exists"""
        if not os.path.exists(self.profile_dir):
            print(f"[ERROR] Chrome profile directory not found: {self.profile_dir}")
            print(f"[INFO] Please copy your Chrome profile to this location.")
            print(f"[INFO] You can find your Chrome profile at:")
            print(f"  Windows: %USERPROFILE%\\AppData\\Local\\Google\\Chrome\\User Data")
            print(f"  macOS: ~/Library/Application Support/Google/Chrome")
            print(f"  Linux: ~/.config/google-chrome")
            return False
        
        profile_path = os.path.join(self.profile_dir, self.profile_name)
        if not os.path.exists(profile_path):
            print(f"[WARNING] Profile '{self.profile_name}' not found in {self.profile_dir}")
            print(f"[INFO] Available profiles:")
            try:
                for item in os.listdir(self.profile_dir):
                    if os.path.isdir(os.path.join(self.profile_dir, item)):
                        print(f"  - {item}")
            except:
                pass
            return False
        
        print(f"[INFO] Chrome profile found: {profile_path}")
        return True
    
    def create_driver(self):
        """Create Chrome WebDriver with profile"""
        if not self.check_profile_exists():
            return None
        
        options = Options()
        options.add_argument(f"--user-data-dir={self.profile_dir}")
        options.add_argument(f"--profile-directory={self.profile_name}")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-default-apps")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        if not self.interactive_mode:
            options.add_argument("--headless")
        
        try:
            print(f"[INFO] Starting Chrome with profile: {self.profile_dir}")
            driver = webdriver.Chrome(service=Service(), options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return driver
        except Exception as e:
            print(f"[ERROR] Failed to create Chrome driver: {e}")
            return None
    
    def extract_cookies_headers(self, driver, base_url):
        """Extract cookies and headers from Selenium session"""
        cookies = {cookie['name']: cookie['value'] for cookie in driver.get_cookies()}
        headers = {
            "User-Agent": driver.execute_script("return navigator.userAgent"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": base_url,
            "Connection": "keep-alive"
        }
        
        # Try to extract tokens from localStorage
        try:
            for token_key in ['access_token', 'auth_token', 'token', 'csrf_token']:
                token = driver.execute_script(f"return localStorage.getItem('{token_key}')")
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                    break
        except:
            pass
        
        return cookies, headers
    
    def save_session_data(self, cookies, headers):
        """Save session data to files"""
        # Save as JSON
        session_data = {"cookies": cookies, "headers": headers}
        with open(self.session_file, "w") as f:
            json.dump(session_data, f, indent=2)
        
        # Save cookies as pickle for Selenium compatibility
        selenium_cookies = [{"name": name, "value": value} for name, value in cookies.items()]
        with open(self.cookie_file, 'wb') as f:
            pickle.dump(selenium_cookies, f)
        
        print(f"[INFO] Session data saved to {self.session_file} and {self.cookie_file}")
    
    def load_session_data(self):
        """Load session data from files"""
        if os.path.exists(self.session_file):
            try:
                with open(self.session_file, "r") as f:
                    session_data = json.load(f)
                self.session_cookies = session_data.get("cookies", {})
                self.session_headers = session_data.get("headers", {})
                print(f"[INFO] Session data loaded from {self.session_file}")
                return True
            except Exception as e:
                print(f"[WARNING] Failed to load session data: {e}")
        return False
    
    def detect_verification_block(self, content):
        max_retries = 3 
        wait_time = 5
        content_lower = content.lower()
        
        just_moment_indicators = self.just_moment_indicators
        unwanted_indicators = self.unwanted_indicators

        # Parse HTML content to extract title and main content

        try:
            soup = BeautifulSoup(content, 'html.parser')
            title = soup.title.string.lower() if soup.title else ''
            main_content = ' '.join([text.strip() for text in soup.stripped_strings])[:500]
        except Exception as e:
            self.log_error(url=self.current_url,
                        error=str(e),
                        message="Error during HTML parsing")
            return {'type': 'error', 'needs_verification': False, 'content': content}

        # Check for verification keywords in title first
        is_verification_keyword = any(indicator in title for indicator in self.verification_keywords)
        is_unwanted_indicator = any(indicator in title for indicator in unwanted_indicators)
        is_just_moment_indicator = any(indicator in title for indicator in just_moment_indicators)

        # Handle verification page with auto-retry logic
        if is_verification_keyword or is_just_moment_indicator:
            self.log_verification_attempt(url=self.current_url, 
                                    type="verification",
                                    message=f"Verification challenge detected: {title}")
            
            # Wait and check if content changes (only if we have a driver)
            if self.driver:
                initial_length = len(content)
                for attempt in range(max_retries):
                    time.sleep(wait_time)  # Wait between checks

                    # Get new page content
                    try:
                        new_content = self.driver.page_source
                        new_soup = BeautifulSoup(new_content, 'html.parser')
                        new_title = new_soup.title.string.lower() if new_soup.title else ''
                        new_length = len(new_content)
                        
                        # Check if content has significantly changed
                        if (new_length > initial_length * 1.5 and  # Content grew significantly
                            not any(indicator in new_title for indicator in just_moment_indicators)):  # No longer verification page
                            
                            # Extract meaningful content to verify it's not an error page
                            try:
                                main_content_new = ' '.join([
                                    text.strip() for text in new_soup.stripped_strings 
                                    if len(text.strip()) > 5
                                ])[:200]
                            except Exception as e:
                                main_content_new = ""
                                self.log_error(url=self.current_url,
                                            error=str(e),
                                            message="Error extracting main content after verification")
                            
                            print(f"[SUCCESS] Verification completed automatically after {attempt + 1} attempts")
                            self.log_success(
                                url=self.current_url,
                                title=new_title,
                                message=f"Auto-verification successful: {main_content_new}..."
                            )
                            return {'type': 'success', 'needs_verification': False, 'content': new_content}
                            
                    except Exception as e:
                        self.log_error(url=self.current_url,
                                    error=str(e),
                                    message="Error during Selenium page source parsing")
                        continue
                
                # If we get here, auto-verification failed
                print(f"[WARNING] Auto-verification failed after {max_retries} attempts")
            
            # Return verification needed
            return {'type': 'cloudflare', 'needs_verification': True, 'content': content}

        # Check for unwanted indicators in title
        if is_unwanted_indicator:
            self.log_verification_attempt(url=self.current_url,
                                    type="blocked",
                                    message=f"Access blocked: {title}")
            return {'type': 'blocked', 'needs_verification': False, 'content': content}
        
        # Check content for verification indicators
        try:
            # Check content for just moment indicators
            if any(indicator in content_lower for indicator in just_moment_indicators):
                self.log_verification_attempt(url=self.current_url,
                                        type="cloudflare",
                                        message=f"Content verification needed: {main_content[:200]}...")
                return {'type': 'cloudflare', 'needs_verification': True, 'content': content}
                
            # Check content for unwanted indicators
            if any(indicator in content_lower for indicator in unwanted_indicators):
                self.log_verification_attempt(url=self.current_url,
                                        type="blocked",
                                        message=f"Content blocked: {main_content[:200]}...")
                return {'type': 'blocked', 'needs_verification': False, 'content': content}
            
            # Check for general verification keywords in content
            if any(keyword in content_lower for keyword in self.verification_keywords):
                self.log_verification_attempt(url=self.current_url, 
                                        type="verification",
                                        message=f"Verification challenge detected in content: {content_lower[:200]}...")
                return {'type': 'verification', 'needs_verification': True, 'content': content}
            
            # No verification needed - successful response
            self.log_success(url=self.current_url,
                            title=title,
                            message="Page loaded successfully")
            return {'type': 'success', 'needs_verification': False, 'content': content}
        except Exception as e:
            self.log_error(url=self.current_url,
                        error=str(e),
                        message="Error during content verification checks")
            return {'type': 'error', 'needs_verification': False, 'content': content}

    def log_success(self, url, title, message):
        """Log successful responses"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'url': url,
            'title': title,
            'message': message,
            'status': 'success'
        }
        with open('success_logs.jsonl', 'a') as f:
            json.dump(log_entry, f)
            f.write('\n')

    def log_error(self, url, error, message):
        """Log errors during verification detection"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'url': url,
            'error': error,
            'message': message,
            'status': 'error'
        }
        with open('error_logs.jsonl', 'a') as f:
            json.dump(log_entry, f)
            f.write('\n')
    
    def handle_selenium_session(self, url):
        """Handle session creation and verification bypass with Selenium"""
        if not self.driver:
            self.driver = self.create_driver()
            if not self.driver:
                return False
        
        try:
            print(f"[INFO] Navigating to {url} with Selenium...")
            self.driver.get(url)
            
            # Wait for page to load
            time.sleep(3)
            
            # Check if verification is needed
            page_content = self.driver.page_source
            if self.detect_verification_block(page_content):
                print(f"[WARNING] Human verification detected on {url}")
                if self.interactive_mode:
                    input("Please complete the verification manually and press Enter to continue...")
                else:
                    print("[INFO] Switching to interactive mode for verification...")
                    # Recreate driver without headless mode
                    self.driver.quit()
                    self.interactive_mode = True
                    self.driver = self.create_driver()
                    if self.driver:
                        self.driver.get(url)
                        input("Please complete the verification manually and press Enter to continue...")
            
            # Extract session data
            cookies, headers = self.extract_cookies_headers(self.driver, url)
            self.save_session_data(cookies, headers)
            self.session_cookies = cookies
            self.session_headers = headers
    
            return True
            
        except Exception as e:
            print(f"[ERROR] Selenium session handling failed: {e}")
            return False
    
    def load_urls(self):
        """Load URLs from the input file"""
        try:
            with open(self.input_file, 'r', encoding='utf-8') as f:
                self.urls = [line.strip() for line in f if line.strip()]
            print(f"[INFO] Loaded {len(self.urls)} URLs from {self.input_file}")
        except FileNotFoundError:
            print(f"[ERROR] File '{self.input_file}' not found")
            sys.exit(1)
        except Exception as e:
            print(f"[ERROR] Loading URLs: {e}")
            sys.exit(1)
    
    def get_random_url(self):
        """Get a random URL from the loaded list"""
        return random.choice(self.urls)
    
    def extract_title(self, html_content):
        """Extract title from HTML content"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            title_tag = soup.find('title')
            return title_tag.get_text().strip() if title_tag else "No title found"
        except Exception as e:
            return f"Title extraction error: {e}"
    
    def save_result(self, content):
        """Append content to result file"""
        try:
            with open(self.output_file, 'a', encoding='utf-8') as f:
                f.write(content + '\n')
        except Exception as e:
            print(f"[ERROR] Writing to result file: {e}")
    
    def save_html(self, html_content, url):
        """Save HTML content to a file"""
        try:
            # Create safe filename from URL
            safe_name = re.sub(r'[^\w\-_.]', '_', urlparse(url).netloc)
            filename = f"response_{safe_name}_{random.randint(0, 999)}.html"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(html_content)
        except Exception as e:
            print(f"[ERROR] Saving HTML file: {e}")
    
    async def fetch_url_with_session(self, session, url):
        """Fetch URL using requests session with cookies/headers"""
        self.tries += 1
        current_try = self.tries
        self.current_url = url  # Set current URL before making request
        
        try:
            # Create request parameters with cookies and headers
            request_params = {
                'headers': self.session_headers,
                'cookies': self.session_cookies,
                'timeout': aiohttp.ClientTimeout(total=30)
            }
            
            async with session.get(url, **request_params) as response:
                html_content = await response.text()
                
                # Check for verification block
                if self.detect_verification_block(html_content):
                    print(f"[WARNING] {current_try} Verification detected for {url}, switching to Selenium...")
                    # Handle with Selenium
                    if self.handle_selenium_session(url):
                        # Retry with new session data
                        request_params['headers'] = self.session_headers
                        request_params['cookies'] = self.session_cookies
                        async with session.get(url, **request_params) as retry_response:
                            html_content = await retry_response.text()
                    else:
                        raise Exception("Failed to bypass verification")
                
                title = self.extract_title(html_content)
                result_line = f"{current_try} {title}"
                print(result_line)
                
                self.save_result(result_line)
                self.save_html(html_content, url)
                
        except asyncio.TimeoutError:
            error_msg = f"{current_try} ERROR Timeout for {url}"
            print(error_msg)
            self.save_result(error_msg)
        except aiohttp.ClientError as e:
            error_msg = f"{current_try} ERROR {str(e)} for {url}"
            print(error_msg)
            self.save_result(error_msg)
        except Exception as e:
            error_msg = f"{current_try} ERROR {str(e)} for {url}"
            print(error_msg)
            self.save_result(error_msg)
    
    def initialize_session(self):
        """Initialize and validate Chrome profile and session data with interactive mode"""
        print("[INFO] Starting interactive session initialization...")
        
        # Step 1: Check if profile exists
        if not self.check_profile_exists():
            print("[ERROR] Please copy your Chrome profile first")
            print("You can use --copy-profile-help for detailed instructions")
            return False
        
        # Temporarily enable interactive mode for initialization
        original_interactive_mode = self.interactive_mode
        self.interactive_mode = True
        
        # Step 2: Create WebDriver in interactive mode
        print("[INFO] Starting Chrome in interactive mode for initialization...")
        self.driver = self.create_driver()
        if not self.driver:
            print("[ERROR] Failed to create Chrome WebDriver")
            return False
        
        try:
            # Step 3: Get a sample URL to extract cookies/headers
            sample_url = self.get_random_url()
            print(f"[INFO] Initializing session with: {sample_url}")
            print("[INFO] Please verify the browser opens correctly and loads the page")
            print("[INFO] If you see any verification prompts, please complete them")
            
            self.driver.get(sample_url)
            
            # Interactive verification
            user_input = input("Did the page load successfully? (y/n): ").lower()
            if user_input != 'y':
                print("[ERROR] Page load verification failed. Please check your profile settings")
                return False
            
            # Step 4: Extract and save session data
            print("[INFO] Extracting cookies and headers...")
            cookies, headers = self.extract_cookies_headers(self.driver, sample_url)
            self.save_session_data(cookies, headers)
            
            # Step 5: Load and verify session data
            print("[INFO] Verifying saved session data...")
            if not self.load_session_data():
                print("[ERROR] Failed to load saved session data")
                return False
            
            print("[SUCCESS] Session initialization complete")
            print("[INFO] You can now run the scraper in non-interactive mode")
            
            # Ask if user wants to continue in interactive mode
            keep_interactive = input("Would you like to keep running in interactive mode? (y/n): ").lower()
            self.interactive_mode = keep_interactive == 'y' or original_interactive_mode
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Session initialization failed: {e}")
            return False
        finally:
            if self.driver and not self.interactive_mode:
                self.driver.quit()
                self.driver = None
            # Restore original interactive mode setting if not keeping interactive
            if not keep_interactive:
                self.interactive_mode = original_interactive_mode
    
    async def run_scraping(self):
        """Run the main scraping process"""
        if not self.urls:
            print("No URLs loaded. Exiting.")
            return
        
        # Add initialization check
        if not os.path.exists(self.session_file):
            if not self.initialize_session():
                print("[ERROR] Failed to initialize session. Please setup Chrome profile first.")
                return
        else:
            if not self.load_session_data():
                if not self.initialize_session():
                    print("[ERROR] Failed to initialize session. Please setup Chrome profile first.")
                    return
        
        connector = aiohttp.TCPConnector(limit=self.concurrency)
        timeout = aiohttp.ClientTimeout(total=30)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Create semaphore to limit concurrency
            semaphore = asyncio.Semaphore(self.concurrency)
            
            async def bounded_fetch(url):
                async with semaphore:
                    await self.fetch_url_with_session(session, url)
            
            # Generate tasks
            tasks = []
            for _ in range(self.total_requests):
                url = self.get_random_url()
                task = asyncio.create_task(bounded_fetch(url))
                tasks.append(task)
            
            # Wait for all tasks to complete
            await asyncio.gather(*tasks, return_exceptions=True)
        
        print(f"\n[INFO] Completed {self.tries} requests")
        
        # Clean up Selenium driver
        if self.driver:
            self.driver.quit()


def main():
    parser = argparse.ArgumentParser(
        description="Hybrid Web Scraper - Async requests with Selenium session management"
    )
    
    parser.add_argument(
        '-i', '--input',
        default='list',
        help='Input file containing URLs (default: list)'
    )
    
    parser.add_argument(
        '-o', '--output',
        default='result',
        help='Output file for results (default: result)'
    )
    
    parser.add_argument(
        '-c', '--concurrency',
        type=int,
        default=5,
        help='Number of concurrent requests (default: 5)'
    )
    
    parser.add_argument(
        '-n', '--requests',
        type=int,
        default=1000,
        help='Total number of requests to make (default: 1000)'
    )
    
    parser.add_argument(
        '--profile-dir',
        default='chrome_profile',
        help='Chrome profile directory (default: chrome_profile)'
    )
    
    parser.add_argument(
        '--profile-name',
        default='Default',
        help='Chrome profile name (default: Default)'
    )
    
    parser.add_argument(
        '--use-selenium',
        action='store_true',
        help='Force use Selenium for initial session establishment'
    )
    
    parser.add_argument(
        '--interactive',
        action='store_true',
        help='Run in interactive mode (non-headless) for manual verification'
    )
    
    parser.add_argument(
        '--session-file',
        default='session_data.json',
        help='Session data file (default: session_data.json)'
    )
    
    parser.add_argument(
        '--cookie-file',
        default='cookies.pkl',
        help='Cookie file (default: cookies.pkl)'
    )
    
    parser.add_argument(
        '--clear-output',
        action='store_true',
        help='Clear output file before starting'
    )
    
    parser.add_argument(
        '--copy-profile-help',
        action='store_true',
        help='Show instructions for copying Chrome profile'
    )
    
    args = parser.parse_args()
    
    # Show profile copy instructions
    if args.copy_profile_help:
        print("=" * 60)
        print("CHROME PROFILE COPY INSTRUCTIONS")
        print("=" * 60)
        print("1. Close all Chrome windows")
        print("2. Find your Chrome profile directory:")
        print("   Windows: %USERPROFILE%\\AppData\\Local\\Google\\Chrome\\User Data")
        print("   macOS: ~/Library/Application Support/Google/Chrome")
        print("   Linux: ~/.config/google-chrome")
        print("3. Copy the entire 'User Data' folder to your working directory")
        print("4. Rename it to 'chrome_profile' (or use --profile-dir)")
        print("5. Note available profiles inside (Default, Profile 1, etc.)")
        print("6. Use --profile-name to specify which profile to use")
        print("=" * 60)
        return
    
    # Clear output file if requested
    if args.clear_output:
        try:
            Path(args.output).unlink(missing_ok=True)
            print(f"[INFO] Cleared output file: {args.output}")
        except Exception as e:
            print(f"[ERROR] Clearing output file: {e}")
    
    # Create and run scraper
    scraper = HybridWebScraper(
        input_file=args.input,
        output_file=args.output,
        concurrency=args.concurrency,
        total_requests=args.requests,
        profile_dir=args.profile_dir,
        profile_name=args.profile_name,
        use_selenium=args.use_selenium,
        interactive_mode=args.interactive,
        session_file=args.session_file,
        cookie_file=args.cookie_file
    )
    
    scraper.load_urls()
    
    try:
        
        asyncio.run(scraper.run_scraping())
    except KeyboardInterrupt:
        print("\n[INFO] Scraping interrupted by user")
        if scraper.driver:
            scraper.driver.quit()
    except Exception as e:
        print(f"[ERROR] During scraping: {e}")
        if scraper.driver:
            scraper.driver.quit()


if __name__ == "__main__":
    main()