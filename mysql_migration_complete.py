#!/usr/bin/env python3
"""
Complete MySQL Migration Script - WMS Serial Transfer & QC System
Creates all necessary tables for Serial Transfer functionality with QC approval workflow
"""

import os
import sys
import logging
import pymysql
from datetime import datetime
from werkzeug.security import generate_password_hash

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MySQLMigration:
    def __init__(self):
        self.connection = None
        self.cursor = None
    
    def get_database_config(self):
        """Get database configuration from environment or user input"""
        config = {
            'host': os.getenv('MYSQL_HOST') or input('MySQL Host (localhost): ') or 'localhost',
            'port': int(os.getenv('MYSQL_PORT') or input('MySQL Port (3306): ') or '3306'),
            'user': os.getenv('MYSQL_USER') or input('MySQL User (root): ') or 'root',
            'password': os.getenv('MYSQL_PASSWORD') or input('MySQL Password: '),
            'database': os.getenv('MYSQL_DATABASE') or input('Database Name (wms): ') or 'wms',
            'charset': 'utf8mb4',
            'autocommit': False
        }
        return config
    
    def connect(self, config):
        """Connect to MySQL database"""
        try:
            self.connection = pymysql.connect(**config)
            self.cursor = self.connection.cursor()
            logger.info(f"✅ Connected to MySQL: {config['database']}")
            return True
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            return False
    
    def create_tables(self):
        """Create all WMS tables with latest schema"""
        
        tables = {
            # 1. Branches/Locations
            'branches': '''
                CREATE TABLE IF NOT EXISTS branches (
                    id VARCHAR(10) PRIMARY KEY,
                    name VARCHAR(100),
                    description VARCHAR(255),
                    branch_code VARCHAR(10) UNIQUE NOT NULL,
                    branch_name VARCHAR(100) NOT NULL,
                    address VARCHAR(255),
                    city VARCHAR(50),
                    state VARCHAR(50),
                    postal_code VARCHAR(20),
                    country VARCHAR(50),
                    phone VARCHAR(20),
                    email VARCHAR(120),
                    manager_name VARCHAR(100),
                    warehouse_codes TEXT,
                    active BOOLEAN DEFAULT TRUE,
                    is_default BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_branch_code (branch_code),
                    INDEX idx_active (active)
                )
            ''',
            
            # 2. Users with comprehensive role management
            'users': '''
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(80) UNIQUE NOT NULL,
                    email VARCHAR(120) UNIQUE NOT NULL,
                    password_hash VARCHAR(256) NOT NULL,
                    first_name VARCHAR(80),
                    last_name VARCHAR(80),
                    role VARCHAR(20) NOT NULL DEFAULT 'user',
                    branch_id VARCHAR(10),
                    branch_name VARCHAR(100),
                    default_branch_id VARCHAR(10),
                    active BOOLEAN DEFAULT TRUE,
                    must_change_password BOOLEAN DEFAULT FALSE,
                    last_login TIMESTAMP NULL,
                    permissions TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_username (username),
                    INDEX idx_email (email),
                    INDEX idx_role (role),
                    INDEX idx_active (active),
                    INDEX idx_branch_id (branch_id)
                )
            ''',
            
            # 3. Serial Number Transfer Documents
            'serial_number_transfers': '''
                CREATE TABLE IF NOT EXISTS serial_number_transfers (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    transfer_number VARCHAR(50) NOT NULL UNIQUE,
                    sap_document_number VARCHAR(50) NULL,
                    status VARCHAR(20) DEFAULT 'draft',
                    user_id INT NOT NULL,
                    qc_approver_id INT NULL,
                    qc_approved_at TIMESTAMP NULL,
                    qc_notes TEXT NULL,
                    from_warehouse VARCHAR(10) NOT NULL,
                    to_warehouse VARCHAR(10) NOT NULL,
                    priority VARCHAR(10) DEFAULT 'normal',
                    notes TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_transfer_number (transfer_number),
                    INDEX idx_status (status),
                    INDEX idx_user_id (user_id),
                    INDEX idx_qc_approver_id (qc_approver_id),
                    INDEX idx_from_warehouse (from_warehouse),
                    INDEX idx_to_warehouse (to_warehouse),
                    INDEX idx_created_at (created_at),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
                    FOREIGN KEY (qc_approver_id) REFERENCES users(id) ON DELETE SET NULL
                )
            ''',
            
            # 4. Serial Transfer Items
            'serial_number_transfer_items': '''
                CREATE TABLE IF NOT EXISTS serial_number_transfer_items (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    serial_transfer_id INT NOT NULL,
                    item_code VARCHAR(50) NOT NULL,
                    item_name VARCHAR(200) NULL,
                    quantity INT NOT NULL,
                    unit_of_measure VARCHAR(10) DEFAULT 'EA',
                    from_warehouse_code VARCHAR(10) NOT NULL,
                    to_warehouse_code VARCHAR(10) NOT NULL,
                    qc_status VARCHAR(20) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_serial_transfer_id (serial_transfer_id),
                    INDEX idx_item_code (item_code),
                    INDEX idx_qc_status (qc_status),
                    FOREIGN KEY (serial_transfer_id) REFERENCES serial_number_transfers(id) ON DELETE CASCADE
                )
            ''',
            
            # 5. Serial Numbers for Transfer Items
            'serial_number_transfer_serials': '''
                CREATE TABLE IF NOT EXISTS serial_number_transfer_serials (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    transfer_item_id INT NOT NULL,
                    serial_number VARCHAR(100) NOT NULL,
                    internal_serial_number VARCHAR(100) NOT NULL,
                    system_serial_number INT NULL,
                    is_validated BOOLEAN DEFAULT FALSE,
                    validation_error TEXT NULL,
                    manufacturing_date DATE NULL,
                    expiry_date DATE NULL,
                    admission_date DATE NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_transfer_item_id (transfer_item_id),
                    INDEX idx_serial_number (serial_number),
                    INDEX idx_is_validated (is_validated),
                    FOREIGN KEY (transfer_item_id) REFERENCES serial_number_transfer_items(id) ON DELETE CASCADE
                )
            '''
        }
        
        # Create tables
        for table_name, table_sql in tables.items():
            try:
                logger.info(f"Creating table: {table_name}")
                self.cursor.execute(table_sql)
                logger.info(f"✅ Table {table_name} created successfully")
            except Exception as e:
                logger.error(f"❌ Error creating table {table_name}: {e}")
                return False
        
        return True
    
    def insert_default_data(self):
        """Insert default data for the WMS system"""
        
        # Default branch
        try:
            self.cursor.execute("""
                INSERT IGNORE INTO branches (id, branch_code, branch_name, name, active, is_default) 
                VALUES ('01', '01', 'Main Branch', 'Main Branch', TRUE, TRUE)
            """)
            logger.info("✅ Default branch inserted")
        except Exception as e:
            logger.warning(f"Branch insertion warning: {e}")
        
        # Default admin user
        try:
            admin_password = generate_password_hash('admin123')
            self.cursor.execute("""
                INSERT IGNORE INTO users (
                    username, email, password_hash, first_name, last_name, 
                    role, branch_id, active, permissions
                ) VALUES (
                    'admin', 'admin@company.com', %s, 'System', 'Administrator',
                    'admin', '01', TRUE, 
                    '{"dashboard": true, "serial_transfer": true, "user_management": true, "qc_dashboard": true}'
                )
            """, (admin_password,))
            logger.info("✅ Default admin user created (username: admin, password: admin123)")
        except Exception as e:
            logger.warning(f"Admin user creation warning: {e}")
        
        # Default QC user
        try:
            qc_password = generate_password_hash('qc123')
            self.cursor.execute("""
                INSERT IGNORE INTO users (
                    username, email, password_hash, first_name, last_name, 
                    role, branch_id, active, permissions
                ) VALUES (
                    'qc_user', 'qc@company.com', %s, 'Quality Control', 'Officer',
                    'qc', '01', TRUE, 
                    '{"dashboard": true, "serial_transfer": true, "qc_dashboard": true}'
                )
            """, (qc_password,))
            logger.info("✅ Default QC user created (username: qc_user, password: qc123)")
        except Exception as e:
            logger.warning(f"QC user creation warning: {e}")
        
        # Default manager user
        try:
            manager_password = generate_password_hash('manager123')
            self.cursor.execute("""
                INSERT IGNORE INTO users (
                    username, email, password_hash, first_name, last_name, 
                    role, branch_id, active, permissions
                ) VALUES (
                    'manager', 'manager@company.com', %s, 'Warehouse', 'Manager',
                    'manager', '01', TRUE, 
                    '{"dashboard": true, "serial_transfer": true, "user_management": true, "qc_dashboard": true}'
                )
            """, (manager_password,))
            logger.info("✅ Default manager user created (username: manager, password: manager123)")
        except Exception as e:
            logger.warning(f"Manager user creation warning: {e}")
        
        return True
    
    def commit_changes(self):
        """Commit all changes to database"""
        try:
            self.connection.commit()
            logger.info("✅ All changes committed to database")
            return True
        except Exception as e:
            logger.error(f"❌ Error committing changes: {e}")
            self.connection.rollback()
            return False
    
    def close_connection(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
        logger.info("📝 Database connection closed")
    
    def run_migration(self):
        """Run the complete migration"""
        print("🚀 Starting WMS MySQL Migration")
        print("=" * 50)
        
        # Get database config
        config = self.get_database_config()
        
        # Connect to database
        if not self.connect(config):
            return False
        
        try:
            # Create tables
            if not self.create_tables():
                return False
            
            # Insert default data
            if not self.insert_default_data():
                return False
            
            # Commit changes
            if not self.commit_changes():
                return False
            
            print("\n🎉 Migration completed successfully!")
            print("=" * 50)
            print("Default Users Created:")
            print("- Admin: username=admin, password=admin123")
            print("- QC User: username=qc_user, password=qc123") 
            print("- Manager: username=manager, password=manager123")
            print("=" * 50)
            print("Your WMS system is ready with:")
            print("✅ User Management with role-based permissions")
            print("✅ Serial Transfer functionality")  
            print("✅ QC Approval workflow")
            print("✅ SAP B1 integration support")
            print("=" * 50)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            return False
        finally:
            self.close_connection()

if __name__ == '__main__':
    migration = MySQLMigration()
    success = migration.run_migration()
    
    if success:
        print("\n🎯 Next Steps:")
        print("1. Update your .env file with MySQL connection details")
        print("2. Configure SAP B1 integration settings")
        print("3. Start your Flask application")
        print("4. Login with admin credentials and begin using the system")
        sys.exit(0)
    else:
        print("\n❌ Migration failed. Please check the logs above.")
        sys.exit(1)