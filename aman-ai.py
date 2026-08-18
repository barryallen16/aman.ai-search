import requests
import json
import xml.etree.ElementTree as ET

url = "https://aman.ai/sitemap.xml"
response = requests.get(url)
res = response.content
with open("sitemap.xml", "wb") as f:
    f.write(res)
tree = ET.parse(res).getroot()
for url in tree:
    link = url[0]
    print(link)
    break
