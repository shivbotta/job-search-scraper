#!/bin/bash
# Daily job search workflow
# Run this once a day to freshen the feed, then use the dashboard to find + apply

set -e
cd "$(dirname "$0")"
source venv/bin/activate

echo "🔄 Scraping fresh jobs from all sources..."
python3 cli.py scrape --skip-google

echo "📊 Scoring jobs (AI + keyword match)..."
python3 cli.py score

echo "✅ Done! Starting dashboard at http://localhost:9009"
echo "   Press Ctrl+C to stop the server"
echo ""
python3 server.py
