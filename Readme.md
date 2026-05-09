<div align="center">

```
██╗███╗   ██╗███████╗██╗ ██████╗ ██╗  ██╗████████╗███████╗██╗      ██████╗ ██╗    ██╗
██║████╗  ██║██╔════╝██║██╔════╝ ██║  ██║╚══██╔══╝██╔════╝██║     ██╔═══██╗██║    ██║
██║██╔██╗ ██║███████╗██║██║  ███╗███████║   ██║   █████╗  ██║     ██║   ██║██║ █╗ ██║
██║██║╚██╗██║╚════██║██║██║   ██║██╔══██║   ██║   ██╔══╝  ██║     ██║   ██║██║███╗██║
██║██║ ╚████║███████║██║╚██████╔╝██║  ██║   ██║   ██║     ███████╗╚██████╔╝╚███╔███╔╝
╚═╝╚═╝  ╚═══╝╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝     ╚══════╝ ╚═════╝  ╚══╝╚══╝ 
```

### Large-Scale Data Preprocessing & Visualization Platform

**Process, transform, and visualize datasets up to 1 GB+ — without ever crashing your server.**

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-2.x-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Dask](https://img.shields.io/badge/Dask-Lazy%20Eval-FC6E26?style=for-the-badge&logo=dask&logoColor=white)](https://dask.org)
[![Parquet](https://img.shields.io/badge/Apache-Parquet-50ABF1?style=for-the-badge&logo=apache&logoColor=white)](https://parquet.apache.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)](LICENSE)

</div>

---

## 🧠 The Problem This Solves

Most data tools fail on large files. Upload a 1 GB CSV to a typical Flask app and it will crash — the server tries to hold the entire file in RAM.

**InsightFlow never does that.**

Every part of the pipeline — uploading, processing, visualizing, downloading — is engineered to work in small, memory-safe chunks. The full file never touches RAM. This makes it production-ready for real-world, large-scale datasets.

---

## ✨ Features

| Category | Capabilities |
|---|---|
| **Upload** | Chunked upload via `Blob.slice()` — 5 MB slices, zero RAM usage |
| **Data Cleaning** | Drop missing values, Mean / Median / Mode / KNN imputation, Duplicate removal, Outlier detection (Z-Score & IQR) |
| **Transformation** | Min-Max Scaling, Standardization, Label Encoding, One-Hot Encoding |
| **Dimensionality Reduction** | PCA, LDA, t-SNE, Feature Selection & Construction |
| **Visualization** | Histograms, Correlation Heatmaps (10×10), Scatter Plots (5,000-row sampled) |
| **Download** | Stream Parquet directly · On-the-fly CSV conversion |
| **State Management** | SQLite-backed recipe persistence — survives browser refreshes |

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        BROWSER (Client)                         │
│                                                                 │
│   File Input ──► Blob.slice() ──► 5 MB Chunks ──► Fetch API    │
│   Schema Table · Recipe Builder · Chart.js Visuals             │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP (chunked)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FLASK BACKEND                              │
│                                                                 │
│   /upload_chunk  → append binary ('ab') to disk                │
│   /execute_recipe → build Dask task graph → Atomic Swap        │
│   /get_scatter_data → sample 5,000 rows across partitions      │
│   /download_csv  → iter_batches() stream transcoding           │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
┌─────────────────────┐        ┌────────────────────────┐
│      DASK ENGINE    │        │    SQLite (State DB)   │
│  Lazy evaluation    │        │  Stores pending recipe │
│  Chunked processing │        │  Survives page refresh │
│  No full RAM load   │        └────────────────────────┘
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   APACHE PARQUET    │
│  Columnar storage   │
│  Compressed binary  │
│  Column-skip reads  │
└─────────────────────┘
```

**Core design principle:** The full dataset is **never** loaded into RAM — at any stage.

---

## 🚀 Getting Started

### Prerequisites

- Python **3.9 or higher**
- `pip` (comes with Python)
- A terminal / command prompt

---

### Step 1 — Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/insightflow.git
cd insightflow
```

---

### Step 2 — Create a Virtual Environment

A virtual environment keeps InsightFlow's dependencies isolated from your system Python.

#### 🍎 macOS / Linux

```bash
# Create the virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Your terminal prompt will change to show (venv)
```

#### 🪟 Windows (Command Prompt)

```cmd
:: Create the virtual environment
python -m venv venv

:: Activate it
venv\Scripts\activate.bat

:: Your terminal prompt will change to show (venv)
```

#### 🪟 Windows (PowerShell)

```powershell
# Create the virtual environment
python -m venv venv

# Activate it
venv\Scripts\Activate.ps1

# If you get a permissions error, run this first:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

> 💡 **To deactivate** the virtual environment later, just type `deactivate` in any terminal.

---

### Step 3 — Install Dependencies

Make sure your virtual environment is **active** (you should see `(venv)` in your terminal), then run:

```bash
pip install -r requirements.txt
```

#### What gets installed:

| Package | Version | Purpose |
|---|---|---|
| `flask` | ≥ 2.3 | Web server & API routing |
| `dask[dataframe]` | ≥ 2024.1 | Lazy, out-of-core data processing |
| `pyarrow` | ≥ 14.0 | Parquet read/write engine |
| `pandas` | ≥ 2.0 | Batch processing within Dask partitions |
| `numpy` | ≥ 1.26 | Numerical operations |
| `scikit-learn` | ≥ 1.4 | PCA, LDA, t-SNE, KNN Imputer, scalers |
| `scipy` | ≥ 1.12 | Z-Score outlier detection |

---

### Step 4 — Run the Application

```bash
python app.py
```

Then open your browser and go to:

```
http://127.0.0.1:5000
```

---

## 📁 Project Structure

```
insightflow/
│
├── app.py                  ← Flask server & all API routes
├── requirements.txt        ← Python dependencies
├── insightflow.db          ← SQLite state database (auto-created)
│
├── templates/
│   └── index.html          ← Main frontend (Vanilla JS + Chart.js)
│
├── uploads/                ← Where uploaded Parquet files are stored
│   └── dataset/            ← Active dataset directory (Parquet partitions)
│
└── README.md
```

---

## 🔬 How the Key Pipelines Work

<details>
<summary><b>📤 Chunked Upload Pipeline</b></summary>

JavaScript slices the file into 5 MB pieces using `Blob.slice()`. Each piece is sent to Flask via `Fetch API`. Flask opens the file in **Append Binary (`ab`) mode** — raw bytes are written directly to disk without decoding into Python objects. RAM usage stays flat at ~0 MB regardless of file size. On the final chunk, the raw binary is converted to Parquet format.

</details>

<details>
<summary><b>🧾 Recipe & State Pipeline</b></summary>

When you select a transformation (e.g., "Min-Max Scaling on column Salary"), no data is processed yet. The action is logged as a lightweight JSON object and pushed to SQLite. This means you can queue up 10 transformations, close the browser, reopen it, and your pending steps are still there — waiting to be executed.

</details>

<details>
<summary><b>⚡ Atomic Swap Pipeline</b></summary>

When you click **Save Changes**, Dask reads the recipe and builds a task graph. Processing happens partition-by-partition, writing results to a **temporary** directory. Only after 100% completion does it perform the Atomic Swap — deleting the old directory and instantly renaming the temp directory to the official path. If the server crashes mid-save, your original data is never touched.

</details>

<details>
<summary><b>📊 Visualization Pipeline</b></summary>

For histograms, Dask computes frequency bins using `dask.array` — only counts, never raw rows, are sent to the browser. For scatter plots, Dask samples exactly **5,000 rows** across all partitions proportionally, making it safe to render regardless of dataset size. For heatmaps, Pearson correlation coefficients are computed and mapped to a Blue → Red color scale.

</details>

<details>
<summary><b>📥 Streaming Download Pipeline</b></summary>

**Parquet:** Flask streams the file directly from disk using `send_file`. **CSV:** The Parquet file is transcoded on-the-fly using `iter_batches()` — each tiny batch is converted to text and appended to the CSV output. The column headers are written exactly once (tracked with a `first_batch` boolean).

</details>

---

## 🛠️ Troubleshooting

**`ModuleNotFoundError`** — Make sure your virtual environment is **activated** before running `pip install` or `python app.py`.

**`Permission denied` on Windows PowerShell** — Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` once, then reactivate the venv.

**Port already in use** — Change the port in `app.py`: `app.run(port=5001)` and visit `http://127.0.0.1:5001`.

**Slow CSV download** — Expected. CSV conversion from Parquet is done on-the-fly. For large files, Parquet download is significantly faster.

---

<!-- ## 🗺️ Roadmap

- [ ] Multi-file merge support
- [ ] ML pipeline integration (model training on processed data)
- [ ] AWS S3 chunked upload support
- [ ] NLP preprocessing module (tokenization, TF-IDF)
- [ ] Dark / Light theme toggle -->


<div align="center">

Built with 🔥 by **Vidit Jain** &nbsp;·&nbsp; [LinkedIn](https://www.linkedin.com/in/jvdt13082/) &nbsp;·&nbsp; 

<!-- [Portfolio](https://yourportfolio.com) -->

*If this project helped you, consider giving it a ⭐ on GitHub!*

</div>