"""
Scripts package for GAIA backend.

This package contains utility scripts that are required at runtime or for setup.

Developer Guidelines:
====================

When adding new scripts that are required at runtime or during setup:

1. **Script Requirements:**
   - Scripts should be self-contained and handle their own imports
   - Use proper error handling and logging
   - Include command-line argument parsing for flexibility
   - Add comprehensive docstrings with usage examples

2. **Adding to setup.sh:**
   - If your script is required during initial setup, add it to the setup.sh script
   - Create a new section in setup.sh with appropriate comments
   - Use the pattern: activate venv, run script, handle errors gracefully
   - Example:
     ```bash
     # --- Your Script Section ---
     echo "🔧 Running your script..."
     cd backend
     if [ -f ".venv/bin/activate" ]; then
         . .venv/bin/activate
     elif [ -f ".venv/Scripts/activate" ]; then
         . .venv/Scripts/activate
     fi
     python scripts/your_script.py --required-args
     cd ..
     ```

3. **Runtime Scripts:**
   - Scripts that need to run during application startup should be added to the lifespan.py
   - Use the startup checks pattern for validation scripts
   - Keep startup checks lightweight and fast

4. **Script Naming:**
   - Use descriptive names that indicate the script's purpose
   - Follow the pattern: `{purpose}_setup.py` or `{purpose}_script.py`
   - Examples: `payment_setup.py`, `seed_models.py`, `validate_config.py`

5. **Documentation:**
   - Include comprehensive docstrings
   - Add usage examples in comments
   - Document required environment variables
   - Explain prerequisites and dependencies

Current Scripts:
================
- payment_setup.py: Sets up subscription plans in the database
- seed_models.py: Manages AI models collection with CRUD operations
"""
