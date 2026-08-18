import xml.etree.ElementTree as ET 

with open("./sitemap.xml", "rb") as f, open("aman-ai-links.txt", "w", encoding="utf-8") as out_file:
    tree = ET.parse(f)
    root = tree.getroot()
    for child in root:
        link = child[0]
        out_file.write(link.text + "\n")

        
