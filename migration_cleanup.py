#!/usr/bin/env python3
"""
Database cleanup migration to remove unwanted modules
Keeps only User, InventoryTransfer, InventoryTransferItem, and SerialTransfer related tables
"""
import logging
from sqlalchemy import text, inspect
from app import app, db

# Configure logging
logging.basicConfig(level=logging.INFO)

def cleanup_database():
    """Remove all unwanted tables and data"""
    
    with app.app_context():
        try:
            # Get database connection
            connection = db.engine.connect()
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            
            logging.info("🧹 Starting database cleanup...")
            logging.info(f"Found {len(existing_tables)} tables in database")
            
            # Tables to keep (only these will remain)
            keep_tables = {
                'users',
                'inventory_transfers', 
                'inventory_transfer_items',
                'serial_number_transfers',
                'serial_number_transfer_items', 
                'serial_number_transfer_serials',
                'branches'  # Keep branches for user management
            }
            
            # Tables to remove (all others will be dropped)
            tables_to_remove = [
                'grpo_documents',
                'grpo_items', 
                'pick_lists',
                'pick_list_items',
                'pick_list_lines',
                'pick_list_bin_allocations',
                'sales_orders',
                'sales_order_lines',
                'inventory_counts',
                'inventory_count_items',
                'barcode_labels',
                'bin_locations',
                'bin_items', 
                'bin_scanning_logs',
                'qr_code_labels',
                'document_number_series'
            ]
            
            # Start transaction
            trans = connection.begin()
            
            try:
                # Disable foreign key constraints temporarily (for SQLite)
                try:
                    connection.execute(text("PRAGMA foreign_keys = OFF"))
                except:
                    pass  # Not SQLite
                
                # Drop unwanted tables that exist
                dropped_count = 0
                for table_name in tables_to_remove:
                    if table_name in existing_tables:
                        try:
                            connection.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
                            logging.info(f"✅ Dropped table: {table_name}")
                            dropped_count += 1
                        except Exception as e:
                            logging.warning(f"⚠️  Could not drop table {table_name}: {e}")
                
                # Re-enable foreign key constraints
                try:
                    connection.execute(text("PRAGMA foreign_keys = ON"))
                except:
                    pass  # Not SQLite
                
                # Commit transaction
                trans.commit()
                
                logging.info(f"🎉 Database cleanup completed! Dropped {dropped_count} unwanted tables")
                logging.info(f"📊 Kept {len(keep_tables)} essential tables: {', '.join(sorted(keep_tables))}")
                
                # Verify remaining tables
                remaining_tables = inspect(db.engine).get_table_names()
                logging.info(f"📋 Remaining tables: {', '.join(sorted(remaining_tables))}")
                
                return True
                
            except Exception as e:
                # Rollback on error
                trans.rollback()
                logging.error(f"❌ Error during cleanup: {e}")
                return False
            
        except Exception as e:
            logging.error(f"❌ Database connection error: {e}")
            return False

def update_user_permissions():
    """Update user permissions to only include available modules"""
    with app.app_context():
        try:
            from models import User
            import json
            
            # New permission structure (only available modules)
            available_permissions = {
                'dashboard': True,
                'inventory_transfer': False, 
                'serial_transfer': False,
                'user_management': False
            }
            
            users = User.query.all()
            updated_count = 0
            
            for user in users:
                try:
                    # Get current permissions
                    current_perms = user.get_permissions()
                    
                    # Create new permissions based on role and available modules
                    new_perms = available_permissions.copy()
                    
                    if user.role == 'admin':
                        # Admin gets all permissions
                        for key in new_perms:
                            new_perms[key] = True
                    elif user.role == 'manager':
                        new_perms.update({
                            'inventory_transfer': True,
                            'serial_transfer': True,
                            'user_management': True
                        })
                    elif user.role == 'user':
                        new_perms.update({
                            'inventory_transfer': True,
                            'serial_transfer': True
                        })
                    
                    # Update user permissions
                    user.set_permissions(new_perms)
                    updated_count += 1
                    
                except Exception as e:
                    logging.warning(f"Could not update permissions for user {user.username}: {e}")
            
            db.session.commit()
            logging.info(f"✅ Updated permissions for {updated_count} users")
            
        except Exception as e:
            logging.error(f"Error updating user permissions: {e}")
            db.session.rollback()

if __name__ == '__main__':
    print("🚀 Starting WMS Database Cleanup Migration")
    print("=" * 50)
    print("This will remove all modules except:")
    print("- User Management")  
    print("- Inventory Transfer (Batch)")
    print("- Serial Transfer")
    print("=" * 50)
    
    # Auto-confirm for non-interactive environment
    success = cleanup_database()
    if success:
        update_user_permissions()
        print("\n🎉 Migration completed successfully!")
        print("The application now contains only the requested modules.")
    else:
        print("\n❌ Migration failed. Check logs for details.")