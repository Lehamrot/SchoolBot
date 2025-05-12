import json

# Load the JSON file
with open("creds.json", "r") as f:
    creds = json.load(f)

# Convert to a single-line escaped string
creds_str = json.dumps(creds)

# Print the result
print(creds_str)
