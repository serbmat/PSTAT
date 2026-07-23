from core.json_db import JsonDB

db = JsonDB("data/database.json")

show = db.find_show_by_normalized_title("witchhatatelier")
print(show)

# db.add_discovered_show("somebrandnewanime")
# db.update_last_download(
#     "witchhatatelier",
#     "S01E08",
#     "2026-05-18T18:30:00+03:00"
# )