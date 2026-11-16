"""Synthetic demo personas (made-up people, made-up portfolios), loaded with `app.cli seed-demo`."""
from datetime import date

DEMO_USERS = [
    {
        "name": "Alex Rivera",
        "persona": "Aggressive tech",
        "risk_tolerance": "high",
        "horizon": "10+ years",
        "interests": ["AI", "semiconductors", "cloud software"],
        "holdings": [
            {"ticker": "NVDA", "purchase_date": date(2024, 6, 3), "shares": 10},
            {"ticker": "AAPL", "purchase_date": date(2025, 1, 4), "amount": 5000},
            {"ticker": "AAPL", "purchase_date": date(2023, 8, 1), "shares": 8},
            {"ticker": "MSFT", "purchase_date": date(2023, 3, 15), "shares": 5},
            {"ticker": "QQQ", "purchase_date": date(2022, 10, 12), "amount": 3000},
        ],
        "watchlist": [("AMD", "AI chip competitor"), ("AVGO", None), ("TSM", "foundry exposure"), ("PLTR", None)],
        "memories": [
            {"kind": "preference", "tags": ["concentration", "risk", "position size"],
             "content": "Wants a heads-up whenever a single position goes above 30% of the portfolio."},
            {"kind": "fact", "tags": ["goals"],
             "content": "Investing for long-term growth; comfortable with large drawdowns."},
        ],
    },
    {
        "name": "Priya Shah",
        "persona": "Balanced ETF",
        "risk_tolerance": "medium",
        "horizon": "15+ years",
        "interests": ["index investing", "international markets", "bonds"],
        "holdings": [
            {"ticker": "VTI", "purchase_date": date(2021, 3, 15), "amount": 10000},
            {"ticker": "VXUS", "purchase_date": date(2021, 3, 15), "amount": 4000},
            {"ticker": "BND", "purchase_date": date(2022, 6, 15), "amount": 5000},
            {"ticker": "VOO", "purchase_date": date(2023, 1, 10), "shares": 10},
        ],
        "watchlist": [("SCHD", None), ("VNQ", "REIT exposure"), ("GLD", "inflation hedge")],
        "memories": [
            {"kind": "preference", "tags": ["index funds", "stock picking"],
             "content": "Prefers low-cost index funds over individual stock picks."},
            {"kind": "fact", "tags": ["rebalancing", "allocation"],
             "content": "Rebalances once a year to roughly 70% stocks and 30% bonds."},
        ],
    },
    {
        "name": "Dan Okafor",
        "persona": "Income focused",
        "risk_tolerance": "low",
        "horizon": "5 years (nearing retirement)",
        "interests": ["dividends", "utilities", "healthcare"],
        "holdings": [
            {"ticker": "JNJ", "purchase_date": date(2022, 4, 1), "shares": 20},
            {"ticker": "KO", "purchase_date": date(2021, 9, 1), "shares": 40},
            {"ticker": "PG", "purchase_date": date(2023, 5, 1), "shares": 15},
            {"ticker": "SCHD", "purchase_date": date(2022, 1, 3), "amount": 6000},  # pre 3-for-1 split
            {"ticker": "O", "purchase_date": date(2023, 2, 1), "shares": 30},
        ],
        "watchlist": [("PEP", None), ("ABBV", "dividend grower"), ("NEE", "utility")],
        "memories": [
            {"kind": "preference", "tags": ["exclusions", "oil", "tobacco"],
             "content": "Does not want oil or tobacco stocks recommended."},
            {"kind": "preference", "tags": ["income", "dividends"],
             "content": "Cares most about reliable dividend income over price growth."},
        ],
    },
]
