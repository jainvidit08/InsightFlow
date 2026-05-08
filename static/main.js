// --- AUTO-RECOVERY ON PAGE LOAD ---
window.addEventListener('DOMContentLoaded', async () => {
    try {
        const response = await fetch('/get_app_state');
        const state = await response.json();

        if (state.status === "success") {
            // 1. Restore the Schema UI
            if (state.schema) {
                document.getElementById('schemaSection').style.display = 'block';
                document.getElementById('rowCountDisplay').textContent = `Total Rows: ${state.row_count.toLocaleString()}`;
                
                const schemaBody = document.getElementById('schemaBody');
                schemaBody.innerHTML = ''; 
                for (const [columnName, dataType] of Object.entries(state.schema)) {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `<td>${columnName}</td><td>${dataType}</td>`;
                    schemaBody.appendChild(tr);
                }
            }

            // 2. Restore the Pending Recipe
            transformationRecipe = state.pending_recipe;
            renderRecipe(); // This will visually rebuild the list!
            
            // Note: We will use state.execution_history in the next step!
            if (state.execution_history) {
                executionHistory = state.execution_history;
                renderHistory();
            }
        }
    } catch (error) {
        console.error("Failed to load application state:", error);
    }
});

document.getElementById('uploadBtn').addEventListener('click', async () => {
    const fileInput = document.getElementById('datasetInput');
    const statusMessage = document.getElementById('statusMessage');
    const progressBar = document.getElementById('progressBar');

    // 1. Validation
    if (fileInput.files.length === 0) {
        statusMessage.textContent = "Error: Please select a file first.";
        return;
    }

    const file = fileInput.files[0];
    
    // 2. Set chunk size to 5 MB 
    const CHUNK_SIZE = 5 * 1024 * 1024; 
    const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
    console.log(totalChunks);
    console.log(file.size);

    statusMessage.textContent = `Starting upload... Total chunks: ${totalChunks}`;
    
    // 3. Loop and Slice
    for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
        const startByte = chunkIndex * CHUNK_SIZE;
        const endByte = Math.min(startByte + CHUNK_SIZE, file.size);
        
        // Extract the chunk
        const chunkBlob = file.slice(startByte, endByte);
        
        // 4. Prepare data for the backend
        const formData = new FormData();
        formData.append('fileChunk', chunkBlob);
        formData.append('fileName', file.name);
        formData.append('chunkIndex', chunkIndex);
        formData.append('totalChunks', totalChunks);

        try {
            statusMessage.textContent = `Uploading chunk ${chunkIndex + 1} of ${totalChunks}...`;
            
            // --- ACTIVATED FETCH: Sending the chunk to Flask ---
            const response = await fetch('/upload_chunk', { 
                method: 'POST', 
                body: formData 
            });
            
            // Read the JSON response from Flask
            const result = await response.json();
            
            // If Flask says it was the last chunk, update the UI
            if (result.status === "complete") {
                statusMessage.textContent = "Upload Complete! Dataset is securely saved on the server.";
                fetchAndDisplaySchema();
            }
            
            // Update UI Progress Bar
            const progress = ((chunkIndex + 1) / totalChunks) * 100;
            progressBar.style.width = progress + '%';
            
        } catch (error) {
            statusMessage.textContent = "Upload failed due to network error.";
            console.error("Error uploading chunk:", error);
            return; 
        }
    }

    statusMessage.textContent = "Frontend Slicing Complete! Ready for Backend Integration (Step 1.3).";
});

// --- RECIPE STATE MANAGEMENT ---
let transformationRecipe = [];

const actionSelect = document.getElementById('actionSelect');
const targetInput = document.getElementById('targetInput');
const recipeList = document.getElementById('recipeList');

// 1. Add a step to the recipe
document.getElementById('addStepBtn').addEventListener('click', () => {
    const action = actionSelect.value;
    const target = targetInput.value.trim();

    if (!target) {
        alert("Please enter a target column name.");
        return;
    }

    // Push the metadata to our state array
    transformationRecipe.push({ action: action, target: target });
    targetInput.value = ''; // Clear input
    
    renderRecipe();
});

// --- NEW DEDICATED SYNC FUNCTION ---
async function syncRecipeToDatabase() {
    try {
        await fetch('/sync_recipe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ recipe: transformationRecipe })
        });
    } catch (error) {
        console.error("Error syncing recipe to database:", error);
    }
}

// --- UPDATED RENDER FUNCTION ---
function renderRecipe() {
    recipeList.innerHTML = ''; // Clear current UI list

    if (transformationRecipe.length === 0) {
        recipeList.innerHTML = '<li class="empty-msg">No transformations added yet.</li>';
        syncRecipeToDatabase(); // FIX: Explicitly sync the empty array to SQLite!
        return;
    }

    transformationRecipe.forEach((step, index) => {
        const li = document.createElement('li');
        let actionText = step.action === 'drop_col' ? 'Drop Column' : 'Fill Missing Values';
        li.textContent = `${index + 1}. ${actionText} -> [${step.target}]`;

        const removeBtn = document.createElement('button');
        removeBtn.textContent = '✖';
        removeBtn.className = 'btn-remove';
        
        removeBtn.onclick = () => {
            transformationRecipe.splice(index, 1);
            renderRecipe(); 
        };

        li.appendChild(removeBtn);
        recipeList.appendChild(li);
    });

    syncRecipeToDatabase(); // Sync normally when items exist
}

// 3. Send the Recipe to the Backend
document.getElementById('executeBtn').addEventListener('click', async () => {
    if (transformationRecipe.length === 0) {
        alert("Your recipe is empty! Add some steps first.");
        return;
    }

    try {
        const response = await fetch('/execute_recipe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ recipe: transformationRecipe })
        });

        const result = await response.json();
        alert(result.message);

        if (result.status === "success") {
            fetchAndDisplaySchema();

            executionHistory.push(...transformationRecipe); 
            renderHistory(); // Update the history UI
            
            // Optional: Clear the recipe list since they were just executed
            transformationRecipe = []; 
            renderRecipe();
        }
        
    } catch (error) {
        console.error("Error sending recipe:", error);
    }
});

// --- SCHEMA VIEWER LOGIC ---
async function fetchAndDisplaySchema() {
    try {
        const response = await fetch('/get_columns');
        const result = await response.json();

        if (result.status === "success") {
            // Show the hidden section
            document.getElementById('schemaSection').style.display = 'block';
            
            // Display row count
            document.getElementById('rowCountDisplay').textContent = 
                `Total Rows: ${result.total_rows.toLocaleString()}`;

            // Populate the table
            const schemaBody = document.getElementById('schemaBody');
            schemaBody.innerHTML = ''; // Clear old data

            // Loop through the dictionary (schema)
            for (const [columnName, dataType] of Object.entries(result.schema)) {
                const tr = document.createElement('tr');
                
                const tdName = document.createElement('td');
                tdName.textContent = columnName;
                
                const tdType = document.createElement('td');
                // Make the data types look a bit cleaner
                tdType.textContent = dataType.replace('object', 'Text/String').replace('float64', 'Decimal').replace('int64', 'Integer');
                
                tr.appendChild(tdName);
                tr.appendChild(tdType);
                schemaBody.appendChild(tr);
            }
        }
    } catch (error) {
        console.error("Error fetching schema:", error);
    }
}

// --- EXECUTION HISTORY STATE & RENDER ---
let executionHistory = [];
const historyList = document.getElementById('historyList');

function renderHistory() {
    historyList.innerHTML = ''; 

    if (executionHistory.length === 0) {
        historyList.innerHTML = '<li class="empty-msg">No transformations executed yet.</li>';
        return;
    }

    executionHistory.forEach((step, index) => {
        const li = document.createElement('li');
        let actionText = step.action === 'drop_col' ? 'Dropped Column' : 'Filled Missing Values';
        li.innerHTML = `✔️ Step ${index + 1}: ${actionText} -> [<b>${step.target}</b>]`;
        historyList.appendChild(li);
    });
}

// --- CLEAR WORKSPACE LOGIC ---
document.getElementById('clearBtn').addEventListener('click', async () => {
    // 1. Safety Alert
    if (!confirm("Are you sure? This will delete the current dataset and all progress!")) {
        return; // User clicked "No", do nothing
    }

    try {
        const response = await fetch('/clear_workspace', { method: 'POST' });
        const result = await response.json();

        if (result.status === "success") {
            // 2. Clear UI instantly
            document.getElementById('schemaSection').style.display = 'none';
            document.getElementById('recipeList').innerHTML = '<li class="empty-msg">No transformations added yet.</li>';
            document.getElementById('historyList').innerHTML = '<li class="empty-msg">No transformations executed yet.</li>';
            document.getElementById('progressBar').style.width = '0%';
            document.getElementById('statusMessage').textContent = "Waiting for dataset...";
            
            // Clear the file input visually
            document.getElementById('datasetInput').value = '';
            
            // 3. Reset local variables
            transformationRecipe = [];
            executionHistory = [];
            
            alert("Workspace is now clean.");
        }
    } catch (error) {
        console.error("Error clearing workspace:", error);
    }
});