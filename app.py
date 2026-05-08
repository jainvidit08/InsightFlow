import os
import pandas as pd
import dask.dataframe as dd
from flask import Flask, render_template, request, jsonify
import json
import sqlite3
import shutil

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_NAME = "app_state.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        # Create the table. We use an auto-incrementing ID.
        conn.execute('''
            CREATE TABLE IF NOT EXISTS AppState (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                schema_json TEXT,
                row_count INTEGER,
                pending_recipe TEXT,
                execution_history TEXT
            )
        ''')
init_db()

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/upload_chunk', methods=['POST'])
@app.route('/upload_chunk', methods=['POST'])
def upload_chunk():
    chunk = request.files['fileChunk']
    file_name = request.form['fileName']
    chunk_index = int(request.form['chunkIndex'])
    total_chunks = int(request.form['totalChunks'])

    save_path = os.path.join(UPLOAD_FOLDER, file_name)

    if chunk_index == 0:
        for existing_file in os.listdir(UPLOAD_FOLDER):
            file_path = os.path.join(UPLOAD_FOLDER, existing_file)
            if os.path.isfile(file_path):
                os.remove(file_path)

    with open(save_path, 'ab') as f:
        f.write(chunk.read())

    if chunk_index == total_chunks - 1:
        try:
            df = pd.read_csv(save_path)
            parquet_filename = file_name.rsplit('.', 1)[0] + '.parquet'
            parquet_path = os.path.join(UPLOAD_FOLDER, parquet_filename)
            df.to_parquet(parquet_path, engine='pyarrow')
            os.remove(save_path)
            
            # --- FIXED DATABASE BLOCK ---
            conn = sqlite3.connect(DB_NAME, timeout=10.0)
            try:
                conn.execute('INSERT INTO AppState (filename, pending_recipe, execution_history) VALUES (?, "[]", "[]")', (parquet_filename,))
                conn.commit()
            finally:
                conn.close()
            # ----------------------------

            return jsonify({"status": "complete", "message": "Converted to Parquet."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    
    return jsonify({"status": "success", "message": f"Chunk {chunk_index} received."})

@app.route('/execute_recipe', methods=['POST'])
def execute_recipe():
    data = request.get_json()
    recipe = data.get('recipe', [])

    if not recipe:
        return jsonify({"status": "error", "message": "Recipe is empty."}), 400

    try:
        # 1. Find the current Parquet file/directory
        files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.parquet')]
        if not files:
            return jsonify({"status": "error", "message": "No dataset found."}), 404
            
        original_filename = files[0]
        original_path = os.path.join(UPLOAD_FOLDER, original_filename)
        
        # Define the temporary path
        temp_path = os.path.join(UPLOAD_FOLDER, f"temp_{original_filename}")

        print(f"\n--- EXECUTING DASK RECIPE ---")
        
        # 2. Load the dataset lazily with Dask
        df = dd.read_parquet(original_path)

        # 3. Apply transformations dynamically based on the JSON array
        for step in recipe:
            action = step.get("action")
            target = step.get("target")
            
            if action == "drop_col":
                print(f"Executing: Dropping column '{target}'")
                df = df.drop(columns=[target])
                
            elif action == "fill_missing":
                print(f"Executing: Filling missing values in '{target}' with 0")
                df[target] = df[target].fillna(0)

        # 4. Execute the computations and save to the TEMP directory
        print("Writing to temporary directory...")
        df.to_parquet(temp_path, engine='pyarrow')

        # 5. THE DIRECTORY SWAP: Safely overwrite the original folder
        print("Performing Directory Swap...")
        if os.path.exists(original_path):
            if os.path.isdir(original_path):
                shutil.rmtree(original_path)
            else:
                os.remove(original_path)
            
        os.rename(temp_path, original_path)

        # --- FIX: UPDATE THE SQLITE DATABASE STATE SAFELY ---
        print("Updating database state...")
        conn = sqlite3.connect(DB_NAME, timeout=10.0)
        try:
            cursor = conn.cursor()
            
            # Get the current execution history from the database
            cursor.execute('SELECT execution_history FROM AppState WHERE id = (SELECT MAX(id) FROM AppState)')
            row = cursor.fetchone()
            current_history = json.loads(row[0]) if row and row[0] else []
            
            # Append the newly executed recipe steps to the history
            current_history.extend(recipe)
            
            # Move the pending steps to history, and clear the pending recipe
            conn.execute('''
                UPDATE AppState 
                SET pending_recipe = "[]", execution_history = ? 
                WHERE id = (SELECT MAX(id) FROM AppState)
            ''', (json.dumps(current_history),))
            conn.commit()
            
        except Exception as e:
            print(f"Error updating execution history in DB: {e}")
            
        finally:
            conn.close()
        # ---------------------------------------------

        print("--- EXECUTION COMPLETE ---")
        return jsonify({"status": "success", "message": "Transformations applied successfully!"})

    except Exception as e:
        print(f"Execution Error: {e}")
        # If something failed, cleanly wipe the orphaned temp folder
        if os.path.exists(temp_path):
            if os.path.isdir(temp_path):
                shutil.rmtree(temp_path)
            elif os.path.isfile(temp_path):
                os.remove(temp_path)

        return jsonify({"status": "error", "message": str(e)}), 500
    
@app.route('/get_columns')
def get_columns():
    conn = None
    try:
        files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.parquet')]
        if not files:
            return jsonify({"status": "error", "message": "No dataset found."}), 404
            
        parquet_path = os.path.join(UPLOAD_FOLDER, files[0])
        df = dd.read_parquet(parquet_path)
        total_rows = len(df)
        schema = {col: str(dtype) for col, dtype in df.dtypes.items()}

        # --- FIXED DATABASE BLOCK ---
        conn = sqlite3.connect(DB_NAME, timeout=10.0)
        conn.execute('UPDATE AppState SET schema_json = ?, row_count = ? WHERE id = (SELECT MAX(id) FROM AppState)', 
                     (json.dumps(schema), total_rows))
        conn.commit()
        # ----------------------------
        
        return jsonify({
            "status": "success", 
            "total_rows": total_rows,
            "schema": schema
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn:
            conn.close()
    
@app.route('/sync_recipe', methods=['POST'])
def sync_recipe():
    """Saves the current pending recipe to the database safely."""
    recipe = request.json.get('recipe', [])
    
    # 1. Open connection with a 10-second timeout queue
    conn = sqlite3.connect(DB_NAME, timeout=10.0)
    
    try:
        conn.execute('UPDATE AppState SET pending_recipe = ? WHERE id = (SELECT MAX(id) FROM AppState)', (json.dumps(recipe),))
        conn.commit()
        return jsonify({"status": "success"})
        
    except Exception as e:
        print(f"Database sync error: {e}")
        return jsonify({"status": "error", "message": "Failed to sync recipe."}), 500
        
    finally:
        # 2. GUARANTEE CLOSURE: Release the lock instantly
        conn.close()

@app.route('/get_app_state', methods=['GET'])
def get_app_state():
    """Restores UI safely by verifying physical file existence."""
    conn = sqlite3.connect(DB_NAME, timeout=10.0)
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT filename, schema_json, row_count, pending_recipe, execution_history FROM AppState ORDER BY id DESC LIMIT 1')
        row = cursor.fetchone()
        
        if row and row[0]:
            filename = row[0]
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            
            # --- NEW: Physical-State Verification ---
            if not os.path.exists(file_path):
                print(f"Database contains {filename}, but physical file is missing. Returning empty state.")
                return jsonify({"status": "empty"})
            # ----------------------------------------
            
            return jsonify({
                "status": "success",
                "filename": filename,
                "schema": json.loads(row[1]) if row[1] else None,
                "row_count": row[2],
                "pending_recipe": json.loads(row[3]) if row[3] else [],
                "execution_history": json.loads(row[4]) if row[4] else []
            })
            
        return jsonify({"status": "empty"})
        
    except Exception as e:
        print(f"Database read error: {e}")
        return jsonify({"status": "error", "message": "Failed to read state."}), 500
    finally:
        conn.close()
        
@app.route('/clear_workspace', methods=['POST'])
def clear_workspace():
    """Wipes the physical disk but leaves the database alone."""
    try:
        if os.path.exists(UPLOAD_FOLDER):
            for f in os.listdir(UPLOAD_FOLDER):
                path = os.path.join(UPLOAD_FOLDER, f)
                if os.path.isdir(path):
                    import shutil
                    shutil.rmtree(path)
                else:
                    os.remove(path)
        return jsonify({"status": "success", "message": "Workspace physical files cleared."})
    except Exception as e:
        print(f"Error clearing workspace: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    
if __name__ == '__main__':
    app.run(debug=True, port=5000)