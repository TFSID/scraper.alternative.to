#!/usr/bin/env python3
"""
Web Scraper CLI Tool
Concurrent HTTP requests with title extraction
"""

import asyncio
import aiohttp
import argparse
import random
import re
from pathlib import Path
from bs4 import BeautifulSoup
import sys


class WebScraper:
    def __init__(self, input_file='list', output_file='result', concurrency=5, total_requests=1000):
        self.input_file = Path(input_file)
        self.output_file = Path(output_file)
        self.concurrency = concurrency
        self.total_requests = total_requests
        self.tries = 0
        self.urls = []
    
    def load_urls(self):
        """Load URLs from the input file"""
        try:
            with open(self.input_file, 'r', encoding='utf-8') as f:
                self.urls = [line.strip() for line in f if line.strip()]
            print(f"Loaded {len(self.urls)} URLs from {self.input_file}")
        except FileNotFoundError:
            print(f"Error: File '{self.input_file}' not found")
            sys.exit(1)
        except Exception as e:
            print(f"Error loading URLs: {e}")
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
            print(f"Error writing to result file: {e}")
    
    def save_html(self, html_content):
        """Save HTML content to a random file"""
        try:
            filename = f"last_result{random.randint(0, 3)}.html"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(html_content)
        except Exception as e:
            print(f"Error saving HTML file: {e}")
    
    async def fetch_url(self, session, url):
        """Fetch a single URL and process the response"""
        self.tries += 1
        current_try = self.tries
        
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                html_content = await response.text()
                title = self.extract_title(html_content)
                
                result_line = f"{current_try} {title}"
                print(result_line)
                
                self.save_result(result_line)
                self.save_html(html_content)
                
        except asyncio.TimeoutError:
            error_msg = f"{current_try} ERROR Timeout"
            print(error_msg)
            self.save_result(error_msg)
        except aiohttp.ClientError as e:
            error_msg = f"{current_try} ERROR {str(e)}"
            print(error_msg)
            self.save_result(error_msg)
        except Exception as e:
            error_msg = f"{current_try} ERROR {str(e)}"
            print(error_msg)
            self.save_result(error_msg)
    
    async def run_scraping(self):
        """Run the main scraping process"""
        if not self.urls:
            print("No URLs loaded. Exiting.")
            return
        
        connector = aiohttp.TCPConnector(limit=self.concurrency)
        timeout = aiohttp.ClientTimeout(total=30)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Create semaphore to limit concurrency
            semaphore = asyncio.Semaphore(self.concurrency)
            
            async def bounded_fetch(url):
                async with semaphore:
                    await self.fetch_url(session, url)
            
            # Generate random URLs and create tasks
            tasks = []
            for _ in range(self.total_requests):
                url = self.get_random_url()
                task = asyncio.create_task(bounded_fetch(url))
                tasks.append(task)
            
            # Wait for all tasks to complete
            await asyncio.gather(*tasks, return_exceptions=True)
        
        print(f"\nCompleted {self.tries} requests")


def main():
    parser = argparse.ArgumentParser(
        description="Web Scraper CLI - Make concurrent HTTP requests and extract page titles"
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
        '--clear-output',
        action='store_true',
        help='Clear output file before starting'
    )
    
    args = parser.parse_args()
    
    # Clear output file if requested
    if args.clear_output:
        try:
            Path(args.output).unlink(missing_ok=True)
            print(f"Cleared output file: {args.output}")
        except Exception as e:
            print(f"Error clearing output file: {e}")
    
    # Create and run scraper
    scraper = WebScraper(
        input_file=args.input,
        output_file=args.output,
        concurrency=args.concurrency,
        total_requests=args.requests
    )
    
    scraper.load_urls()
    
    try:
        asyncio.run(scraper.run_scraping())
    except KeyboardInterrupt:
        print("\nScraping interrupted by user")
    except Exception as e:
        print(f"Error during scraping: {e}")


if __name__ == "__main__":
    main()