# clean_db.py
"""
Database Cleaning Utility

This script provides a command-line interface to clean old records from either the
SQLite or PostgreSQL database used by the Bills-Calc application.

It removes records with a scrape_date older than a specified cutoff date.

Execution Commands:
-------------------
# To clean the SQLite database:
python clean_db.py --db-type sqlite --cutoff-date YYYY-MM-DD

# To clean the PostgreSQL database:
python clean_db.py --db-type postgres --cutoff-date YYYY-MM-DD

Example:
python clean_db.py --db-type sqlite --cutoff-date 2020-01-01
"""

import argparse
import logging
import os
from db_manager import SQLiteDBManager
from postgres_manager import PostgresDBManager

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """
    Main function to parse arguments and run the database cleaning process.
    """
    parser = argparse.ArgumentParser(
        description="Clean old records from the specified database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  # Clean SQLite records older than January 1, 2020
  python clean_db.py --db-type sqlite --cutoff-date 2020-01-01

  # Clean PostgreSQL records older than January 1, 2020
  python clean_db.py --db-type postgres --cutoff-date 2020-01-01
""",
    )
    parser.add_argument(
        "--db-type",
        type=str,
        choices=["sqlite", "postgres"],
        required=True,
        help="The type of the database to clean ('sqlite' or 'postgres').",
    )
    parser.add_argument(
        "--cutoff-date",
        type=str,
        required=True,
        help="The cutoff date in 'YYYY-MM-DD' format. Records older than this date will be deleted.",
    )
    args = parser.parse_args()

    logger.info(f"🚀 Starting database cleaning process for '{args.db_type}'...")

    db_manager = None
    try:
        if args.db_type == "sqlite":
            db_manager = SQLiteDBManager()
        elif args.db_type == "postgres":
            # Check for POSTGRES_URI before attempting to connect
            if not os.environ.get("POSTGRES_URI"):
                logger.error(
                    "❌ POSTGRES_URI environment variable is not set. Cannot connect to PostgreSQL."
                )
                return
            db_manager = PostgresDBManager()

        if not db_manager:
            logger.error(f"Invalid database type specified: {args.db_type}")
            return

        # Clean old records
        deleted_count = db_manager.clean_old_records(args.cutoff_date)

        # Vacuum the database if records were deleted
        if deleted_count > 0:
            logger.info("Optimizing database after deletion...")
            db_manager.vacuum_database()

        logger.info(
            f"✅ Cleaning process completed successfully for '{args.db_type}'. {deleted_count} records were deleted."
        )

    except Exception as e:
        logger.error(
            f"💥 An error occurred during the cleaning process: {e}", exc_info=True
        )


if __name__ == "__main__":
    main()
