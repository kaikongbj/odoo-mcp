#!/usr/bin/env python3
"""
Simple test script to verify SafeDatabaseManager class structure
"""

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_safe_db_manager_structure():
    """Test that SafeDatabaseManager has the expected methods"""
    try:
        # Import just the SafeDatabaseManager class definition
        with open('mcp_server/services/fast_mcp_service.py', 'r') as f:
            content = f.read()
        
        # Check for key components
        required_components = [
            'class SafeDatabaseManager:',
            'def __init__(self, pool_size=10, connection_timeout=30):',
            'def _get_connection_pool(self, db_name):',
            'def _create_connection(self, db_name):',
            'def _get_connection(self, db_name):',
            'def _release_connection(self, db_name, cursor):',
            'def _check_connection_health(self, cursor):',
            'def get_env(self, db_name=None):',
            'async def execute_with_env(self, operation, *args, **kwargs):',
            'def cleanup_connections(self, db_name=None):',
            'async def _safe_execute_with_env(self, operation, *args, **kwargs):',
        ]
        
        missing_components = []
        for component in required_components:
            if component not in content:
                missing_components.append(component)
        
        if missing_components:
            print("❌ Missing components:")
            for component in missing_components:
                print(f"  - {component}")
            return False
        else:
            print("✅ All required components found in SafeDatabaseManager")
            
        # Check for implementation functions
        impl_functions = [
            '_query_odoo_model_impl',
            '_get_odoo_record_impl', 
            '_create_odoo_record_impl',
            '_update_odoo_record_impl',
            '_delete_odoo_record_impl',
            '_get_odoo_model_metadata_impl',
            '_list_resources_impl',
            '_get_resource_content_impl',
            '_get_server_info_impl',
            '_get_resource_by_id_impl'
        ]
        
        missing_impl = []
        for func in impl_functions:
            if f'def {func}(' not in content:
                missing_impl.append(func)
        
        if missing_impl:
            print("❌ Missing implementation functions:")
            for func in missing_impl:
                print(f"  - {func}")
            return False
        else:
            print("✅ All implementation functions found")
            
        return True
        
    except Exception as e:
        print(f"❌ Error testing SafeDatabaseManager: {e}")
        return False

if __name__ == "__main__":
    print("Testing SafeDatabaseManager implementation...")
    success = test_safe_db_manager_structure()
    if success:
        print("\n🎉 SafeDatabaseManager implementation looks good!")
    else:
        print("\n❌ SafeDatabaseManager implementation has issues")
    
    sys.exit(0 if success else 1)