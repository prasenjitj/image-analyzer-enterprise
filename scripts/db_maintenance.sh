#!/bin/bash
# Database maintenance script using direct SQL operations
# Alternative to Python script for environments with dependency issues

set -e  # Exit on any error

# Configuration - update these variables
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-imageprocessing}"
DB_USER="${DB_USER:-prasenjitjana}"
DB_PASSWORD="${DB_PASSWORD:-testpass123}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to run SQL commands
run_sql() {
    local sql="$1"
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "$sql"
}

# Function to show database statistics
show_stats() {
    echo -e "${BLUE}📊 Database Statistics:${NC}"
    run_sql "
    SELECT 'processing_batches' as table_name, COUNT(*) as count FROM processing_batches
    UNION ALL
    SELECT 'processing_chunks', COUNT(*) FROM processing_chunks
    UNION ALL
    SELECT 'url_analysis_results', COUNT(*) FROM url_analysis_results;
    "

    echo -e "\n${BLUE}📈 Batch Status Breakdown:${NC}"
    run_sql "
    SELECT status, COUNT(*) as count
    FROM processing_batches
    GROUP BY status
    ORDER BY count DESC;
    "

    echo -e "\n${BLUE}📅 Data Age:${NC}"
    run_sql "
    SELECT
        MIN(created_at) as oldest_record,
        MAX(created_at) as newest_record,
        EXTRACT(day FROM NOW() - MIN(created_at)) as days_oldest
    FROM processing_batches;
    "
}

# Function to clear old batches
clear_old() {
    local days="${1:-30}"
    echo -e "${YELLOW}🗑️  Clearing batches older than $days days...${NC}"

    # Show what will be deleted
    echo "Records to be deleted:"
    run_sql "
    SELECT
        COUNT(*) as batches_to_delete,
        COUNT(DISTINCT pc.chunk_id) as chunks_to_delete,
        COUNT(DISTINCT uar.result_id) as results_to_delete
    FROM processing_batches pb
    LEFT JOIN processing_chunks pc ON pb.batch_id = pc.batch_id
    LEFT JOIN url_analysis_results uar ON pb.batch_id = uar.batch_id
    WHERE pb.created_at < NOW() - INTERVAL '$days days';
    "

    read -p "Continue with deletion? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Operation cancelled."
        exit 0
    fi

    # Delete in correct order
    echo "Deleting associated analysis results..."
    run_sql "
    DELETE FROM url_analysis_results
    WHERE batch_id IN (
        SELECT batch_id FROM processing_batches
        WHERE created_at < NOW() - INTERVAL '$days days'
    );
    "

    echo "Deleting associated chunks..."
    run_sql "
    DELETE FROM processing_chunks
    WHERE batch_id IN (
        SELECT batch_id FROM processing_batches
        WHERE created_at < NOW() - INTERVAL '$days days'
    );
    "

    echo "Deleting old batches..."
    run_sql "
    DELETE FROM processing_batches
    WHERE created_at < NOW() - INTERVAL '$days days';
    "

    echo -e "${GREEN}✅ Cleared batches older than $days days${NC}"
}

# Function to clear failed batches
clear_failed() {
    echo -e "${YELLOW}🗑️  Clearing failed/cancelled batches...${NC}"

    # Show what will be deleted
    echo "Records to be deleted:"
    run_sql "
    SELECT
        COUNT(*) as batches_to_delete,
        COUNT(DISTINCT pc.chunk_id) as chunks_to_delete,
        COUNT(DISTINCT uar.result_id) as results_to_delete
    FROM processing_batches pb
    LEFT JOIN processing_chunks pc ON pb.batch_id = pc.batch_id
    LEFT JOIN url_analysis_results uar ON pb.batch_id = uar.batch_id
    WHERE pb.status IN ('failed', 'cancelled');
    "

    read -p "Continue with deletion? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Operation cancelled."
        exit 0
    fi

    # Delete in correct order
    echo "Deleting associated analysis results..."
    run_sql "
    DELETE FROM url_analysis_results
    WHERE batch_id IN (
        SELECT batch_id FROM processing_batches
        WHERE status IN ('failed', 'cancelled')
    );
    "

    echo "Deleting associated chunks..."
    run_sql "
    DELETE FROM processing_chunks
    WHERE batch_id IN (
        SELECT batch_id FROM processing_batches
        WHERE status IN ('failed', 'cancelled')
    );
    "

    echo "Deleting failed/cancelled batches..."
    run_sql "
    DELETE FROM processing_batches
    WHERE status IN ('failed', 'cancelled');
    "

    echo -e "${GREEN}✅ Cleared failed/cancelled batches${NC}"
}

# Function to clear all data
clear_all() {
    echo -e "${RED}💣 WARNING: This will delete ALL data permanently!${NC}"
    echo -e "${RED}This operation cannot be undone!${NC}"

    # Show current data count
    echo "Current data counts:"
    run_sql "
    SELECT 'processing_batches' as table_name, COUNT(*) as count FROM processing_batches
    UNION ALL
    SELECT 'processing_chunks', COUNT(*) FROM processing_chunks
    UNION ALL
    SELECT 'url_analysis_results', COUNT(*) FROM url_analysis_results;
    "

    read -p "Are you absolutely sure you want to delete ALL data? (type 'YES' to confirm): " confirmation
    if [[ "$confirmation" != "YES" ]]; then
        echo "Operation cancelled."
        exit 0
    fi

    echo "Deleting all data..."
    run_sql "DELETE FROM url_analysis_results;"
    run_sql "DELETE FROM processing_chunks;"
    run_sql "DELETE FROM processing_batches;"

    echo -e "${GREEN}✅ All data cleared${NC}"
}

# Function to optimize database
optimize_db() {
    echo -e "${BLUE}🔧 Optimizing database...${NC}"

    echo "Running VACUUM ANALYZE..."
    run_sql "VACUUM ANALYZE;"

    echo "Updating table statistics..."
    run_sql "ANALYZE;"

    echo -e "${GREEN}✅ Database optimization completed${NC}"
}

# Function to create backup
create_backup() {
    local backup_dir="${1:-./backups}"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$backup_dir/backup_$timestamp.sql.gz"

    mkdir -p "$backup_dir"

    echo -e "${BLUE}📦 Creating database backup...${NC}"
    PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" | gzip > "$backup_file"

    echo -e "${GREEN}✅ Backup created: $backup_file${NC}"
    echo -e "${BLUE}💡 Restore with: gunzip < $backup_file | PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME${NC}"
}

# Main script logic
case "${1:-help}" in
    "stats")
        show_stats
        ;;
    "clear-old")
        clear_old "${2:-30}"
        ;;
    "clear-failed")
        clear_failed
        ;;
    "clear-all")
        clear_all
        ;;
    "optimize")
        optimize_db
        ;;
    "backup")
        create_backup "${2:-./backups}"
        ;;
    "help"|*)
        echo "Database Maintenance Script for Enterprise Image Analyzer"
        echo ""
        echo "Usage: $0 <command> [options]"
        echo ""
        echo "Commands:"
        echo "  stats                    Show database statistics"
        echo "  clear-old [days]         Clear batches older than N days (default: 30)"
        echo "  clear-failed             Clear failed/cancelled batches"
        echo "  clear-all                Clear ALL data (dangerous!)"
        echo "  optimize                 Run database optimization (VACUUM, ANALYZE)"
        echo "  backup [dir]             Create database backup (default: ./backups)"
        echo "  help                     Show this help message"
        echo ""
        echo "Environment variables (or edit script):"
        echo "  DB_HOST=$DB_HOST"
        echo "  DB_PORT=$DB_PORT"
        echo "  DB_NAME=$DB_NAME"
        echo "  DB_USER=$DB_USER"
        echo "  DB_PASSWORD=***"
        echo ""
        echo "Examples:"
        echo "  $0 stats"
        echo "  $0 clear-old 90"
        echo "  $0 backup /mnt/backups"
        ;;
esac