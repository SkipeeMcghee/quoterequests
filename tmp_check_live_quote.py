import urllib.request

url = 'http://127.0.0.1:5000/quote-request'
with urllib.request.urlopen(url) as response:
    html = response.read().decode('utf-8', errors='replace')
print('checkbox-grid' in html, 'checkbox-card' in html, '<input' in html)
print('--- start ---')
print(html[:1200])
