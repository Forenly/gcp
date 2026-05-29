#!/usr/bin/env python3
"""
Seed script to load curated robotic mower catalog, yard archetypes, 
and historical deployment plans into MongoDB Atlas.
"""

import os
import json
import sys
from pathlib import Path
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, PyMongoError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB = os.getenv("MONGODB_DB", "lawn_advisor")

if not MONGODB_URI:
    print("Error: MONGODB_URI environment variable is not set.", file=sys.stderr)
    print("Please configure it in a .env file or your environment.", file=sys.stderr)
    sys.exit(1)

# Paths to seed files
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
SEED_DIR = REPO_ROOT / "data" / "seed"

SEED_FILES = {
    "mower_models": SEED_DIR / "mower_models.json",
    "yards": SEED_DIR / "yards.json",
    "deployment_plans": SEED_DIR / "deployment_plans.json",
}

def load_json_file(file_path):
    """Safely load and return JSON file contents."""
    if not file_path.exists():
        print(f"Error: Seed file not found at {file_path}", file=sys.stderr)
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {file_path}: {e}", file=sys.stderr)
        return None

def main():
    print(f"Connecting to MongoDB Atlas at database: '{MONGODB_DB}'...")
    try:
        # Connect to MongoDB
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        # Force a connection check
        client.admin.command("ping")
        db = client[MONGODB_DB]
        print("Successfully connected to MongoDB!")
    except ConnectionFailure:
        print("Error: Could not connect to MongoDB Atlas. Check your connection string or network/firewall.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected connection error: {e}", file=sys.stderr)
        sys.exit(1)

    # Process each seed file
    for collection_name, file_path in SEED_FILES.items():
        print(f"\n--- Seeding Collection: '{collection_name}' ---")
        
        data = load_json_file(file_path)
        if data is None:
            print(f"Skipping {collection_name} due to load error.")
            continue
            
        if not isinstance(data, list):
            print(f"Error: Seed data in {file_path.name} must be a JSON array. Skipping.", file=sys.stderr)
            continue
            
        collection = db[collection_name]
        
        # Count before seeding
        count_before = collection.count_documents({})
        print(f"Current document count: {count_before}")
        
        # Prompt / clear existing
        print(f"Clearing existing documents in '{collection_name}'...")
        collection.delete_many({})
        
        if len(data) == 0:
            print(f"Seed file {file_path.name} was empty. Collection is now clean and empty.")
            continue
            
        print(f"Inserting {len(data)} documents into '{collection_name}'...")
        try:
            # Insert data
            result = collection.insert_many(data)
            print(f"Successfully inserted {len(result.inserted_ids)} documents.")
            
            # Setup helpful indexes
            setup_indexes(collection_name, collection)
            
        except PyMongoError as e:
            print(f"Error seeding collection '{collection_name}': {e}", file=sys.stderr)

    print("\nDatabase seeding completed successfully!")

def setup_indexes(collection_name, collection):
    """Configure search indexes for optimal agent retrieval."""
    try:
        if collection_name == "mower_models":
            collection.create_index("brand")
            collection.create_index("price_tier")
            collection.create_index([("max_yard_area_sqm", 1), ("max_slope_pct", 1)])
            print("Indexes created for 'mower_models' on (brand), (price_tier), and (max_yard_area_sqm, max_slope_pct).")
            
        elif collection_name == "yards":
            collection.create_index("terrain")
            collection.create_index([("area_sqm", 1), ("slope_pct", 1)])
            print("Indexes created for 'yards' on (terrain) and (area_sqm, slope_pct).")
            
        elif collection_name == "deployment_plans":
            collection.create_index("yard_id")
            collection.create_index("mower_id")
            print("Indexes created for 'deployment_plans' on (yard_id) and (mower_id).")
            
    except PyMongoError as e:
         print(f"Warning: Could not create indexes on '{collection_name}': {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
