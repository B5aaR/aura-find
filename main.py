import json
import sys
import os

def search_arch_wiki(query):
    script_dir = os.path.dirname(os.path.realpath(__file__))
    json_path = os.path.join(script_dir, "data", "real_db.json")

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except FileNotFoundError:
        print("Error: Run build_db.py first to generate the database.")
        return

    query = query.lower()
    results = []

    # Search through every app's name, description, and category
    for app in db.get("apps", []):
        if (query in app["name"]) or (query in app["desc"].lower()) or (query in app["category"].lower()):
            results.append(app)

    if results:
        print(f"\nFound {len(results)} offline results for '{query}':")
        print("-" * 60)
        # Limit to top 15 results so it doesn't flood the terminal
        for app in results[:15]:
            print(f" \033[92m{app['name']}\033[0m ({app['category']})")
            print(f"    ↳ {app['desc'][:80]}...") # Truncate long descriptions

        if len(results) > 15:
            print(f"\n...and {len(results) - 15} more. Try being more specific!")
        print("-" * 60)
    else:
        print(f"\nNo offline results found for '{query}'.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <search_term>")
        print("Example: python main.py 'video editor'")
    else:
        # Join all arguments so users can search for phrases like "video editor"
        search_query = " ".join(sys.argv[1:])
        search_arch_wiki(search_query)
