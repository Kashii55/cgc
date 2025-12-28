# CGC Card Scraper

A Scrapy spider to scrape certificate images and details from [CGC Cards](https://www.cgccards.com/).

## Overview

This spider automates the process of:
- Reading certificate IDs from a CSV file
- Looking up certificates on cgccards.com
- Extracting all associated images from certificate detail pages
- Downloading images locally
- Exporting image URLs and metadata to a CSV file

## Features

- **Batch Processing**: Process multiple certificate IDs from a CSV input file
- **Image Extraction**: Automatically finds and extracts all images from certificate pages
- **Image Download**: Saves images locally organized by certificate ID
- **CSV Export**: Outputs `cgc_images.csv` with image URLs for each certificate
- **Proxy Support**: Includes ZenRows proxy integration for working around Cloudflare/anti-bot protections
- **Error Handling**: Built-in error logging and fallback mechanisms

## Requirements

- Python 3.7+
- Scrapy 2.0+
- A ZenRows API key (for proxy support)

## Installation

1. **Install dependencies**:
   ```bash
   pip install scrapy
   ```

2. **Obtain a ZenRows proxy** (optional but recommended):
   - Sign up at [ZenRows](https://www.zenrows.com/)
   - Get your proxy URL from the dashboard

## Configuration

Edit [cgc/spiders/cgc.py](cgc/spiders/cgc.py) to configure:

### Required Settings

**`csv_path`** (line ~29)
- Path to your input CSV file containing certificate IDs
- Default: `CGC.csv`
- CSV must have a column named `Cert` containing certificate IDs

**`proxy_url`** (line ~32)
- Your ZenRows HTTP proxy URL
- Replace `"Enter_Your_ZenRows_Proxy_Here"` with your actual proxy
- Format: `http://[API-KEY]@[PROXY-SERVER]:[PORT]`
- Leave as-is if using without proxy (not recommended for cgccards.com)

### Optional Settings

**`images_store`** (line ~35)
- Directory where downloaded images will be saved
- Default: `images`
- Images are organized as: `images/<cert_id>/image_1.jpg`, `image_2.jpg`, etc.

## Input CSV Format

Create a CSV file with certificate IDs (e.g., `CGC.csv`):

```csv
Cert
123456789
987654321
555666777
```

The CSV must have a header row. The spider looks for a column named `Cert`.

## Usage

Run the spider from the project root directory:

```bash
scrapy crawl cgc
```

Or using the runspider command:

```bash
python -m scrapy crawl cgc
```

## Output

### CSV Output (`cgc_images.csv`)

A CSV file containing certificate IDs and their associated image URLs:

```csv
cert,image_1,image_2,image_3,...
123456789,https://example.com/img1.jpg,https://example.com/img2.jpg,...
987654321,https://example.com/img3.jpg,...
```

### Downloaded Images

Images are saved to: `images/<cert_id>/image_<number>.<extension>`

Example structure:
```
images/
├── 123456789/
│   ├── image_1.jpg
│   ├── image_2.jpg
│   └── image_3.png
└── 987654321/
    ├── image_1.jpg
    └── image_2.jpg
```

## How It Works

1. **Homepage Parsing** (`parse_home`): 
   - Fetches the CGC Cards homepage
   - Identifies the certificate lookup form and input field
   - Reads certificate IDs from the input CSV

2. **Form Submission** (`parse_cert`):
   - Submits the lookup form for each certificate ID
   - Routes requests through the ZenRows proxy

3. **Image Extraction**:
   - Parses certificate detail pages
   - Extracts image URLs from `div.certlookup-images-item` elements
   - Handles both `<a href>` and `<img src>` tags

4. **Image Download** (`save_image`):
   - Downloads each image to the local `images/` directory
   - Automatically detects file extensions
   - Organizes by certificate ID

5. **CSV Export**:
   - Yields item dicts that are automatically written to `cgc_images.csv`
   - Uses Scrapy's FEEDS setting

## Logging

The spider logs important information to the console:

- Certificate lookups initiated
- Number of images found per certificate
- Image download confirmations
- Errors and warnings

View logs by running the spider normally. Increase verbosity with:

```bash
scrapy crawl cgc -L DEBUG
```

## Troubleshooting

### No images found for certificates

- **Cause**: Certificate IDs may be invalid or not found on cgccards.com
- **Solution**: Verify certificate IDs in your CSV and test manually on the website

### Proxy errors

- **Cause**: Invalid ZenRows proxy URL
- **Solution**: Check your ZenRows dashboard for the correct proxy URL and update `proxy_url` in the script

### CSV not found

- **Cause**: Incorrect path in `csv_path` variable
- **Solution**: Use absolute path or ensure the CSV file is in the correct directory relative to the spider

### Request timeouts

- **Cause**: Network issues or server slow to respond
- **Solution**: Increase `DOWNLOAD_TIMEOUT` in custom_settings (currently 30 seconds)

## Advanced Configuration

Edit `custom_settings` dictionary in the spider for:

- **`CONCURRENT_REQUESTS`**: Number of simultaneous requests (default: 2)
- **`DOWNLOAD_TIMEOUT`**: Request timeout in seconds (default: 30)
- **`RETRY_TIMES`**: Number of retries on failure (default: 2)
- **`USER_AGENT`**: Identify your spider to servers

## License

This project is provided as-is for educational and personal use.

## Notes

- Respect the website's terms of service and robots.txt
- Use appropriate delays between requests
- Consider the website's server load when scraping
- A proxy service like ZenRows is recommended to handle Cloudflare protections
