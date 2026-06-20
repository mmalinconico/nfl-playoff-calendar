import json
import requests

url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=20270113-20270119"

response = requests.get(url)
response.raise_for_status()

data = response.json()

print(json.dumps(data["events"][0], indent=2))
