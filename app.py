import os
import pandas as pd
import dask.dataframe as dd
from flask import Flask, render_template, request, jsonify
import json
import sqlite3
import shutil
from dask_ml.preprocessing import StandardScaler
from dask_ml.decomposition import PCA
import dask.array as da
import numpy as np

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
        # 3. Apply transformations dynamically based on the JSON array
        for step in recipe:
            action = step.get("action")
            target = step.get("target")
            strategy = step.get("strategy")
            
            if action == "drop_col":
                print(f"Executing: Dropping column '{target}'")
                df = df.drop(columns=[target])
                
            elif action == "remove_duplicates":
                print("Executing: Removing exact duplicates")
                df = df.drop_duplicates()
                
            elif action == "fill_missing":
                print(f"Executing: Filling missing values in '{target}' using {strategy}")
                if strategy == "zero":
                    df[target] = df[target].fillna(0)
                elif strategy == "mean":
                    mean_val = df[target].mean().compute()
                    df[target] = df[target].fillna(mean_val)
                elif strategy == "median":
                    # Dask computes approximate quantiles for speed on large data
                    median_val = df[target].quantile(0.5).compute() 
                    df[target] = df[target].fillna(median_val)
                    
            elif action == "remove_outliers":
                print(f"Executing: Removing outliers in '{target}' using {strategy}")
                if strategy == "iqr":
                    Q1 = df[target].quantile(0.25).compute()
                    Q3 = df[target].quantile(0.75).compute()
                    IQR = Q3 - Q1
                    lower_bound = Q1 - 1.5 * IQR
                    upper_bound = Q3 + 1.5 * IQR
                    df = df[(df[target] >= lower_bound) & (df[target] <= upper_bound)]
            
            elif action == "scale_data":
                print(f"Executing: Scaling '{target}' using {strategy}")
                if strategy == "minmax":
                    # [cite: 1099] Min-Max Scaling: Squashes values into a [0, 1] range.
                    col_min = df[target].min().compute()
                    col_max = df[target].max().compute()
                    # Prevent division by zero if all numbers in the column are identical
                    if col_max != col_min:
                        df[target] = (df[target] - col_min) / (col_max - col_min)
                        
                elif strategy == "standard":
                    # [cite: 1100] Standardization: Centers data around a mean of 0.
                    col_mean = df[target].mean().compute()
                    col_std = df[target].std().compute()
                    if col_std != 0:
                        df[target] = (df[target] - col_mean) / col_std

            elif action == "encode_data":
                print(f"Executing: Encoding '{target}' using {strategy}")
                # First, tell Dask to scan the column to identify all unique text categories
                df[target] = df[target].astype('category').cat.as_known()
                
                if strategy == "label":
                    # [cite: 1100] Label Encoding: Converts text labels into sequential numbers (0, 1, 2...)
                    df[target] = df[target].cat.codes
                    
                elif strategy == "onehot":
                    # [cite: 1101] One-Hot Encoding: Creates binary columns and drops the original text column
                    df = dd.get_dummies(df, columns=[target])
            
            # --- UPGRADED CODE: SELECTIVE PCA WITH SAFE NAMING ---
            elif action == "apply_pca":
                n_components = int(step.get("components", 2))
                target_cols_str = step.get("target", "all")
                
                # 1. Determine which columns to use
                if target_cols_str == "all":
                    numeric_cols = list(df.select_dtypes(include=['number']).columns)
                else:
                    requested_cols = [c.strip() for c in target_cols_str.split(",")]
                    numeric_cols = [c for c in requested_cols if c in df.columns]
                
                print(f"Executing: Applying PCA to {numeric_cols} to reduce to {n_components} components")
                
                if len(numeric_cols) > n_components:
                    from dask_ml.preprocessing import StandardScaler
                    from dask_ml.decomposition import PCA
                    
                    # 2. Standardize only the selected columns
                    scaler = StandardScaler()
                    df_scaled = scaler.fit_transform(df[numeric_cols])
                    dask_array = df_scaled.to_dask_array(lengths=True)
                    
                    # 3. Fit and Transform
                    pca = PCA(n_components=n_components)
                    pca_result = pca.fit_transform(dask_array)
                    
                    # --- FIX: DYNAMIC NAMESPACE CALCULATION ---
                    # Scan existing columns to find the highest PCA number so we don't overwrite!
                    existing_pca_nums = [
                        int(c.split('_')[-1]) for c in df.columns 
                        if c.startswith("PCA_Component_") and c.split('_')[-1].isdigit()
                    ]
                    start_idx = max(existing_pca_nums) if existing_pca_nums else 0
                    
                    # 4. Create new PCA DataFrame using the safe offset numbers
                    pca_cols = [f"PCA_Component_{start_idx + i + 1}" for i in range(n_components)]
                    df_pca = dd.from_dask_array(pca_result, columns=pca_cols, index=df.index)
                    # ------------------------------------------

                    # 5. Drop the old columns and append the new safely-named super-columns
                    df = df.drop(columns=numeric_cols)
                    for col_name in pca_cols:
                        df[col_name] = df_pca[col_name]
                        
                else:
                    print("Skipping PCA: Not enough numeric columns to reduce.")
            # ---------------------------------------------
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

@app.route('/get_column_summary', methods=['GET'])
def get_column_summary():
    """Lazily calculates histogram bins or category counts for a specific column."""
    col_name = request.args.get('column')
    
    files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.parquet')]
    if not files:
        return jsonify({"status": "error", "message": "No dataset found."}), 404

    parquet_path = os.path.join(UPLOAD_FOLDER, files[0])
    
    # 1. Read metadata lazily
    df = dd.read_parquet(parquet_path)

    if col_name not in df.columns:
        return jsonify({"status": "error", "message": "Column not found."}), 404

    # 2. NUMERIC COLUMNS: Calculate Histogram Bins
    if pd.api.types.is_numeric_dtype(df[col_name].dtype):
        # Drop missing values to prevent math errors
        clean_col = df[col_name].dropna()
        
        # We must compute min/max first to establish the boundary of our bins
        col_min = clean_col.min().compute()
        col_max = clean_col.max().compute()

        if pd.isna(col_min) or col_min == col_max:
             return jsonify({"status": "success", "labels": [str(col_min)], "data": [len(clean_col)]})

        # Convert to Dask Array and compute 10 histogram bins
        col_array = clean_col.to_dask_array(lengths=True)
        counts, bin_edges = da.histogram(col_array, bins=10, range=[col_min, col_max])
        
        counts_result = counts.compute() # Trigger the actual calculation
        
        # Format the X-axis labels (e.g., "18 to 25")
        labels = [f"{int(bin_edges[i])} to {int(bin_edges[i+1])}" for i in range(len(counts_result))]

        return jsonify({
            "status": "success",
            "type": "numeric",
            "labels": labels,
            "data": counts_result.tolist()
        })
        
    # 3. TEXT/CATEGORICAL COLUMNS: Calculate Top 10 Value Counts
    else:
        # Count the occurrences of each text label and grab the top 10
        value_counts = df[col_name].value_counts().compute().head(10)
        return jsonify({
            "status": "success",
            "type": "categorical",
            "labels": value_counts.index.astype(str).tolist(),
            "data": value_counts.values.tolist()
        })
    
@app.route('/get_correlation_matrix', methods=['GET'])
def get_correlation_matrix():
    """Calculates a Pearson correlation matrix for all numeric columns."""
    try:
        files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.parquet')]
        if not files:
            return jsonify({"status": "error", "message": "No dataset found."}), 404

        parquet_path = os.path.join(UPLOAD_FOLDER, files[0])
        # LAZY LOAD: Dask only reads numeric columns for this math
        df = dd.read_parquet(parquet_path)
        numeric_df = df.select_dtypes(include=['number'])
        
        if len(numeric_df.columns) < 2:
            return jsonify({"status": "error", "message": "Need at least 2 numeric columns."}), 400

        # Compute the N x N matrix
        corr_matrix = numeric_df.corr().compute()
        
        return jsonify({
            "status": "success",
            "columns": corr_matrix.columns.tolist(),
            "values": corr_matrix.values.tolist()
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get_scatter_data', methods=['GET'])
def get_scatter_data():
    """Lazily samples 5,000 rows across two columns for a scatter plot."""
    col_x = request.args.get('x')
    col_y = request.args.get('y')
    
    try:
        files = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith('.parquet')]
        if not files:
            return jsonify({"status": "error", "message": "No dataset found."}), 404

        parquet_path = os.path.join(UPLOAD_FOLDER, files[0])
        
        # 1. Load data lazily
        df = dd.read_parquet(parquet_path)

        if col_x not in df.columns or col_y not in df.columns:
            return jsonify({"status": "error", "message": "Selected columns not found."}), 404

        # 2. Isolate the two columns and drop NaNs (scatter plots break on nulls)
        subset = df[[col_x, col_y]].dropna()
        
        # 3. Calculate the fraction to get roughly 5,000 rows
        total_rows = len(subset)
        if total_rows == 0:
            return jsonify({"status": "success", "data": []})
            
        frac = min(5000.0 / total_rows, 1.0)

        # 4. Use Dask to sample across all partitions and compute the result
        print(f"Sampling {frac*100:.2f}% of data for scatter plot...")
        sampled_df = subset.sample(frac=frac).compute()
        
        # 5. Format the data exactly how Chart.js expects it: [{'x': 1, 'y': 2}, ...]
        chart_data = [{"x": row[col_x], "y": row[col_y]} for _, row in sampled_df.iterrows()]

        return jsonify({
            "status": "success",
            "data": chart_data
        })
        
    except Exception as e:
        print(f"Scatter Plot Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    
if __name__ == '__main__':
    app.run(debug=True, port=5000)