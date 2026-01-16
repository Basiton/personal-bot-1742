#!/usr/bin/env python3
"""
Migration script to populate account_stats table from existing comment_history
Run this once after updating main.py
"""
import sqlite3
from datetime import datetime

SQLITE_DB = "bot_data.db"

def migrate_data():
    """Migrate existing comment_history to account_stats"""
    try:
        conn = sqlite3.connect(SQLITE_DB)
        cursor = conn.cursor()
        
        # Check if account_stats table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='account_stats'")
        if not cursor.fetchone():
            print("❌ account_stats table does not exist. Please run the bot first to create it.")
            return
        
        # Check if there's already data in account_stats
        cursor.execute("SELECT COUNT(*) FROM account_stats")
        existing_count = cursor.fetchone()[0]
        
        if existing_count > 0:
            print(f"⚠️  account_stats already has {existing_count} records.")
            response = input("Do you want to continue and import from comment_history? (y/n): ")
            if response.lower() != 'y':
                print("Migration cancelled.")
                return
        
        # Import from comment_history
        cursor.execute("SELECT phone, channel, comment, date FROM comment_history")
        comments = cursor.fetchall()
        
        if not comments:
            print("ℹ️  No data in comment_history to migrate.")
            return
        
        print(f"📊 Found {len(comments)} records in comment_history")
        print("🔄 Migrating to account_stats...")
        
        migrated = 0
        for phone, channel, comment, date in comments:
            try:
                cursor.execute(
                    """INSERT INTO account_stats (phone, channel, event_type, timestamp, success, error_message) 
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (phone, channel, 'comment_sent', date, 1, '')
                )
                migrated += 1
            except Exception as e:
                print(f"⚠️  Error migrating record for {phone}: {e}")
        
        conn.commit()
        print(f"✅ Successfully migrated {migrated} records to account_stats")
        
        # Show stats
        cursor.execute("SELECT COUNT(DISTINCT phone) FROM account_stats")
        unique_phones = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT channel) FROM account_stats")
        unique_channels = cursor.fetchone()[0]
        
        print(f"📈 Statistics:")
        print(f"   • Unique accounts: {unique_phones}")
        print(f"   • Unique channels: {unique_channels}")
        print(f"   • Total events: {migrated}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Migration error: {e}")

if __name__ == "__main__":
    print("🚀 Starting stats migration...")
    migrate_data()
    print("✅ Migration complete!")
