import os

# Fixed test values, set before the app is imported (the real .env never overrides these).
os.environ["API_JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["ALLOWED_EMAILS"] = "test@example.com"