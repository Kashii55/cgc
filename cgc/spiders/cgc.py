# cgc_spider.py
#
# Scrapy spider to:
# - Read certificate IDs from a CSV (path configured in csv_path)
# - Visit https://www.cgccards.com/, find the input[type="tel"] on the page,
#   submit the lookup button (button[name="lookup"]) for each cert (using the same form page)
# - On the certificate detail page extract all images under div.certlookup-images-item a
#   (handles anchors with hrefs and <img> tags)
# - Save the image URLs to a CSV (image_1, image_2, ...) and also download images
#   into folder images/<cert>/image_1.<ext>, image_2.<ext>, ...
# - Routes all requests through the provided ZenRows proxy to work around Cloudflare/recaptcha.
#
# Usage:
# scrapy runspider cgc_spider.py
#
# The spider uses the FEEDS setting to create "cgc_images.csv" in the current directory.
# Adjust csv_path and proxy_url variables below as needed.

import os
import csv
import errno
from urllib.parse import urlsplit, unquote, urljoin
import mimetypes

import scrapy
from scrapy import FormRequest, Request


class CgcSpider(scrapy.Spider):
    name = "cgc"
    allowed_domains = ["cgccards.com"]
    start_urls = ["https://www.cgccards.com/"]

    # ======= CONFIGURE THESE =======
    # Path to CSV with Cert column (as provided by user)
    csv_path = r"CGC.csv"

    # ZenRows HTTP proxy provided by user (used as HTTP proxy)
    proxy_url = "Enter_Your_ZenRows_Proxy_Here"

    # Folder where images will be saved (relative to current working dir)
    images_store = "images"
    # ===============================

    # Make spider produce a CSV with the scraped image URLs automatically
    custom_settings = {
        "FEEDS": {
            # output CSV file
            "cgc_images.csv": {
                "format": "csv",
                # if you want to change encoding/fields or filename, do it here
            }
        },
        # be polite / identify yourself (change if you want)
        "USER_AGENT": "Mozilla/5.0 (compatible; CGC-Scraper/1.0; +https://www.example.com)",
        # reduce concurrent requests to reduce chance of triggering anti-bot
        "CONCURRENT_REQUESTS": 2,
        "DOWNLOAD_TIMEOUT": 30,
        # disable retries if you want, or increase depending on stability
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 2,
        # do not use the built-in ImagesPipeline; we save images manually
        "LOG_LEVEL": "INFO",
    }

    def start_requests(self):
        # Start by fetching the homepage (we will reuse this response to submit the form)
        for url in self.start_urls:
            # route via proxy
            yield Request(
                url,
                callback=self.parse_home,
                errback=self.errback_log,
                meta={"proxy": self.proxy_url},
            )

    def parse_home(self, response):
        """
        Parse the homepage, find the input[type="tel"] name and the form containing it,
        then load the CSV and submit the lookup for each cert.
        """
        self.logger.info("Fetched homepage, locating telephone input & form...")

        # Try to find the input[name] for input[type="tel"]
        input_elem = response.css('input[type="tel"]')
        input_name = input_elem.attrib.get("name") if input_elem else None
        input_id = input_elem.attrib.get("id") if input_elem else None

        # Find the form that contains the input (best-effort)
        # form_sel = response.css('form:has(input[type="tel"])') or response.css('form')
        form_sel = response.xpath('//form[.//input[@type="tel"]]')

        form_action = None
        form_method = "POST"
        if form_sel:
            # pick the first matching form
            form = form_sel[0]
            form_action = form.attrib.get("action", "")
            form_method = form.attrib.get("method", "POST").upper()

        if input_name:
            self.logger.info(f"Found input[type='tel'] name='{input_name}'")
        elif input_id:
            self.logger.warning(f"Found input[type='tel'] with id='{input_id}' but no name attribute. Will attempt to submit using form action.")
        else:
            self.logger.warning("Could not find input[type='tel'] name or id on the page. Will attempt fallback submission.")

        # Read certs from CSV
        certs = []
        try:
            with open(self.csv_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                # accept file with header "Cert" or similar; fall back to first column if necessary
                if "Cert" in reader.fieldnames:
                    for row in reader:
                        cert = row.get("Cert")
                        if cert:
                            certs.append(cert.strip())
                else:
                    # fallback: take first column values
                    first_field = reader.fieldnames[0]
                    for row in reader:
                        cert = row.get(first_field)
                        if cert:
                            certs.append(cert.strip())
        except FileNotFoundError:
            self.logger.error(f"CSV file not found at {self.csv_path}. Make sure path is correct.")
            return
        except Exception as e:
            self.logger.error(f"Error reading CSV: {e}")
            return

        if not certs:
            self.logger.error("No certs found in CSV - nothing to do.")
            return

        self.logger.info(f"Found {len(certs)} cert(s) in CSV. Submitting lookups...")

        # Use FormRequest.from_response when input_name is present (keeps cookies, hidden fields, etc).
        # Otherwise build a POST/GET to the form action (best-effort).
        for cert in certs:
            meta = {"cert": cert, "proxy": self.proxy_url}
            if input_name:
                # Use clickdata for the submit button named "lookup" as requested by user
                try:
                    req = FormRequest.from_response(
                        response,
                        formdata={input_name: cert},
                        clickdata={"name": "lookup"},
                        callback=self.parse_cert,
                        errback=self.errback_log,
                        meta=meta,
                        dont_filter=True,
                    )
                    yield req
                except Exception as e:
                    # fallback: construct manual request if FormRequest.from_response fails
                    self.logger.warning(f"FormRequest.from_response failed: {e}. Falling back to manual form POST.")
                    yield from self._manual_form_submit(cert, form_action, form_method, meta, response)
            else:
                # manual submission
                yield from self._manual_form_submit(cert, form_action, form_method, meta, response)

    def _manual_form_submit(self, cert, form_action, form_method, meta, response):
        """
        Fallback manual form submission if input name is not available.
        We will try a POST to the form action (or homepage if action empty) with a field name 'cert' (best-effort).
        """
        target = response.url if not form_action else urljoin(response.url, form_action)
        # conservative fallback field name guesses
        candidate_field_names = ["cert", "certificate", "serial", "lookup", "search", "q"]
        # try to detect any possible field names on the form inputs
        found_names = response.css('form input::attr(name)').getall() or []
        # prioritize detected names
        candidate_field_names = found_names + candidate_field_names

        # Try each candidate as the form field key until we get a successful-looking response
        for field_name in candidate_field_names:
            formdata = {field_name: cert}
            self.logger.info(f"Attempting manual {form_method} to {target} with field '{field_name}'")
            if form_method == "GET":
                yield Request(
                    url=target,
                    method="GET",
                    callback=self.parse_cert,
                    errback=self.errback_log,
                    meta={**meta, "formdata": formdata},
                    dont_filter=True,
                    params=formdata if hasattr(Request, "params") else None,  # Scrapy Request doesn't support params; kept for readability
                )
            else:
                # Use FormRequest to POST to the action url directly
                yield FormRequest(
                    url=target,
                    formdata=formdata,
                    method="POST",
                    callback=self.parse_cert,
                    errback=self.errback_log,
                    meta=meta,
                    dont_filter=True,
                )
            # we only schedule one attempt per field_name -- do not loop too many times
            break

    def parse_cert(self, response):
        """
        Parse the certificate detail page and extract images.
        Yields:
            - a dict containing cert and image_1, image_2, ...
            - Requests to download each image (saved by save_image)
        """
        cert = response.meta.get("cert")
        self.logger.info(f"Parsing detail page for cert {cert} (URL: {response.url})")

        # collect image URLs from anchors under div.certlookup-images-item
        imgs = []
        # anchors with hrefs (sometimes they link to large image file)
        hrefs = response.css('div.certlookup-images-item a::attr(href)').getall() or []
        # images inside the anchors or directly
        srcs = response.css('div.certlookup-images-item a img::attr(src)').getall() or []
        # also try direct img tags under that div
        direct_srcs = response.css('div.certlookup-images-item img::attr(src)').getall() or []

        for u in hrefs + srcs + direct_srcs:
            if not u:
                continue
            u = response.urljoin(u)
            if u not in imgs:
                imgs.append(u)

        if not imgs:
            self.logger.info(f"No images found for cert {cert}.")
        else:
            self.logger.info(f"Found {len(imgs)} image(s) for cert {cert}.")

        # Build item with image URLs (image_1, image_2, ...)
        item = {"cert": cert}
        for i, img_url in enumerate(imgs):
            item[f"image_{i+1}"] = img_url

        # yield the CSV row (FEEDS will write cgc_images.csv automatically)
        yield item

        # Schedule image downloads (saved to disk)
        for i, img_url in enumerate(imgs):
            # pass index and cert to save_image
            yield Request(
                img_url,
                callback=self.save_image,
                errback=self.errback_log,
                meta={"cert": cert, "index": i + 1, "proxy": self.proxy_url},
                dont_filter=True,
            )

    def save_image(self, response):
        """
        Save image binary to disk: images/<cert>/image_<index>.<ext>
        Attempt to infer extension from URL or Content-Type header, fallback to .jpg
        """
        cert = response.meta.get("cert", "unknown")
        index = response.meta.get("index", 0)

        # ensure folder exists
        folder = os.path.join(self.images_store, cert)
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            if e.errno != errno.EEXIST:
                self.logger.error(f"Failed to create directory {folder}: {e}")
                return

        # attempt to determine extension
        def _ext_from_url(u):
            path = urlsplit(unquote(u)).path
            base = os.path.basename(path)
            if "." in base:
                return os.path.splitext(base)[1]
            return ""

        ext = _ext_from_url(response.url)
        if not ext:
            # look at Content-Type header
            ctype = response.headers.get("Content-Type", b"").decode("utf-8", errors="ignore")
            ext = mimetypes.guess_extension(ctype.split(";")[0].strip()) or ""
        if not ext:
            ext = ".jpg"

        filename = f"image_{index}{ext}"
        path = os.path.join(folder, filename)

        try:
            with open(path, "wb") as f:
                f.write(response.body)
            self.logger.info(f"Saved image for cert {cert}: {path}")
        except Exception as e:
            self.logger.error(f"Failed to save image {path}: {e}")

    def errback_log(self, failure):
        # Log requests errors (useful for debugging proxy/Cloudflare problems)
        self.logger.error(repr(failure))
