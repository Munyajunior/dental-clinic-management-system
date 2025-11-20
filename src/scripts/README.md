# Initialize the database (creates tables and RLS)
python scripts/migrate.py init

# Create a new migration
python scripts/migrate.py create "Add new feature"

# Run migrations
python scripts/migrate.py upgrade

# Show migration history
python scripts/migrate.py history

# Show current revision
python scripts/migrate.py current