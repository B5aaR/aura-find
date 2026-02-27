import os
import glob
from bs4 import BeautifulSoup
import json

def build_database():
    base_dir = "/usr/share/doc/arch-wiki/html/en/"

    # The offline wiki saves subpages either in a folder, with underscores, or URL-encoded %2F
    print("Hunting for Arch Wiki application sub-pages...")
    files_to_parse = glob.glob(os.path.join(base_dir, "List_of_applications*.html")) + \
                     glob.glob(os.path.join(base_dir, "List_of_applications", "*.html")) + \
                     glob.glob(os.path.join(base_dir, "List_of_applications%2F*.html"))

    # Remove any duplicates just in case
    files_to_parse = list(set(files_to_parse))

    if not files_to_parse:
        print("Error: Could not find the application sub-pages.")
        return

    db = {"apps": []}

    for html_path in files_to_parse:
        print(f" -> Parsing {os.path.basename(html_path)}...")
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f, "lxml")
        except FileNotFoundError:
            continue

        current_category = "General"

        for tag in soup.find_all(['h2', 'h3', 'h4', 'li']):
            # Update category when we hit a heading
            if tag.name in ['h2', 'h3', 'h4']:
                headline = tag.find(class_="mw-headline")
                if headline:
                    current_category = headline.text.strip()

            # Extract the app when we hit a list item
            elif tag.name == 'li':
                a_tag = tag.find('a')
                # Arch Wiki usually bolds the package name in these lists
                b_tag = tag.find('b')

                if a_tag and tag.text:
                    # Prefer the bolded text, fallback to the link text
                    app_name = b_tag.text.strip() if b_tag else a_tag.text.strip()
                    description = tag.text.replace(app_name, "", 1).strip(" \t\n—–-")

                    # Filter out garbage data: Needs a name, a decent description, and no massive spaces in the package name
                    if app_name and len(description) > 5 and len(app_name) < 30 and "\n" not in app_name:
                        db["apps"].append({
                            "name": app_name.lower(),
                            "desc": description[:150], # Keep descriptions concise
                            "category": current_category
                        })

    script_dir = os.path.dirname(os.path.realpath(__file__))
    output_path = os.path.join(script_dir, "data", "real_db.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4)

    print(f"\nSUCCESS! Extracted {len(db['apps'])} applications into data/real_db.json")

if __name__ == "__main__":
    build_database()
