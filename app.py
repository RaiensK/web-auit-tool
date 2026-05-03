from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

app = Flask(__name__)

def _check_single_link(full_url):
    try:
        r = requests.head(full_url, timeout=5, allow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code in (404, 403, 500, 410):
            return {"type": f"HTTP {r.status_code}", "value": full_url,
                    "detail": f"Link returned status {r.status_code}"}
    except requests.exceptions.Timeout:
        return {"type": "Timeout", "value": full_url, "detail": "Request timed out"}
    except Exception:
        return {"type": "Unreachable", "value": full_url, "detail": "Could not reach URL"}
    return None


def check_broken_links(soup, base_url):
    issues = []
    links = soup.find_all('a', href=True)
    urls_to_check = []

    for a in links:
        href = a['href'].strip()
        if not href:
            issues.append({"type": "Empty href", "value": "(empty)", "detail": "Anchor tag has no href value"})
            continue
        if href.startswith('mailto:'):
            if '@' not in href[7:]:
                issues.append({"type": "Malformed mailto", "value": href, "detail": "Invalid email in mailto link"})
            continue
        if href.startswith('tel:'):
            if len(href) < 6:
                issues.append({"type": "Malformed tel", "value": href, "detail": "Invalid phone in tel link"})
            continue
        if href.startswith('#') or href.startswith('javascript:'):
            continue
        urls_to_check.append(urljoin(base_url, href))

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_check_single_link, url): url for url in urls_to_check}
        for future in as_completed(futures):
            result = future.result()
            if result:
                issues.append(result)

    return issues, len(links)



def check_html_health(soup):
    issues = []
    # Missing alt on images
    for img in soup.find_all('img'):
        if not img.get('alt') and img.get('alt') != '':
            issues.append({"type": "Missing alt", "value": img.get('src', '(no src)'),
                           "detail": "Image is missing alt attribute"})
    # Empty button text
    for btn in soup.find_all('button'):
        if not btn.get_text(strip=True) and not btn.find('i') and not btn.find('svg'):
            issues.append({"type": "Empty button", "value": str(btn)[:80],
                           "detail": "Button has no visible text or icon"})
    # Empty link text
    for a in soup.find_all('a'):
        if not a.get_text(strip=True) and not a.find('img') and not a.find('i') and not a.find('svg'):
            issues.append({"type": "Empty link text", "value": a.get('href', '(no href)'),
                           "detail": "Anchor tag has no visible text"})
    # Empty title tag
    title = soup.find('title')
    if not title or not title.get_text(strip=True):
        issues.append({"type": "Empty title", "value": "<title>",
                       "detail": "Page title tag is missing or empty"})
    return issues


def check_seo(soup, url):
    issues = []
    # Title
    title = soup.find('title')
    if not title or not title.get_text(strip=True):
        issues.append({"type": "Missing title", "value": url, "detail": "Page has no <title> tag"})
    # Meta description
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if not meta_desc or not meta_desc.get('content', '').strip():
        issues.append({"type": "Missing meta description", "value": url,
                       "detail": "No meta description found"})
    # H1
    h1s = soup.find_all('h1')
    if not h1s:
        issues.append({"type": "Missing H1", "value": url, "detail": "Page has no H1 tag"})
    elif len(h1s) > 1:
        issues.append({"type": "Multiple H1s", "value": url,
                       "detail": f"Page has {len(h1s)} H1 tags, should have only 1"})
    # Canonical
    canonical = soup.find('link', attrs={'rel': 'canonical'})
    if not canonical:
        issues.append({"type": "Missing canonical", "value": url,
                       "detail": "No canonical link tag found"})
    # Duplicate meta descriptions (check all meta tags)
    all_meta = soup.find_all('meta', attrs={'name': 'description'})
    if len(all_meta) > 1:
        issues.append({"type": "Duplicate meta description", "value": url,
                       "detail": f"Found {len(all_meta)} meta description tags"})
    return issues


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/scan", methods=["POST"])
def scan():
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    start = time.time()
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception as e:
        return jsonify({"error": f"Could not fetch URL: {str(e)}"}), 400

    soup = BeautifulSoup(resp.text, "html.parser")

    link_issues, links_checked = check_broken_links(soup, url)
    html_issues = check_html_health(soup)
    seo_issues = check_seo(soup, url)

    all_issues = link_issues + html_issues + seo_issues
       # Time to complete scan
    elapsed = round(time.time() - start, 2)

    total_checks = links_checked + len(soup.find_all('img')) + 5  # 5 SEO checks
    passed = total_checks - len(all_issues)
    # atgriežm visu JavaScript
    return jsonify({
        "links_checked": links_checked,
        "issues_found": len(all_issues),
        "passed_checks": max(passed, 0),
        "scan_time": elapsed,
        "link_issues": link_issues,
        "html_issues": html_issues,
        "seo_issues": seo_issues,
    })


if __name__ == "__main__":
    app.run(debug=True)
