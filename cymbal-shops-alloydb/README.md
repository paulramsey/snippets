# Cymbal Shops StyleSearch AlloyDB AI Demo

This project demonstrates the AI capabilities of Google Cloud AlloyDB for PostgreSQL, particularly focusing on hybrid search (SQL + vector + full-text search) using a sample e-commerce dataset (Cymbal Shops).

![image](./assets/img/stylesearch-demo-screenshot.png)

> **IMPORTANT:** This notebook leverages Preview features in AlloyDB AI. **[Sign up for the preview](https://docs.google.com/forms/d/e/1FAIpQLSfJ9vHIJ79nI7JWBDELPFL75pDQa4XVZQ2fxShfYddW0RwmLw/viewform)** before running this notebook.

## Overview

The project provides resources to set up and explore AlloyDB AI features:

1.  **Data Preparation & Backend Setup**: A Jupyter notebook guides you through preparing the dataset and setting up the AlloyDB database. You can optionally skip the data prep by executing the shortcut notebook instead, which quickly provisions the backend with pre-prepared data.
2.  **Demo Application**: A sample Angular frontend and Node.js backend application showcase hybrid search functionality in a user interface.

## Features Demonstrated

* **Vector Embeddings**: Generating and storing embeddings for product data within AlloyDB.
* **pgvector Extension**: Utilizing the `pgvector` extension for efficient vector similarity search.
* **Full-Text Search**: Combining traditional full-text search with vector search for hybrid results.
* **AlloyDB AI Integration**: Showcasing how to leverage AlloyDB's integrated multimodal AI features.
* **Cloud Run Deployment**: Sample deployment scripts for the frontend and backend on Google Cloud Run.

## Project Structure

```
cymbal-shops-alloydb/
│
├── cymbal_shops_hybrid_search_alloydb_data_prep.ipynb  # Notebook 1: Full data prep (embeddings, FTS, etc.)
├── cymbal_shops_stylesearch_demo_shortcut.ipynb      # Notebook 2: Quick backend setup using pre-prepared data
│
├── demo_app/                                           # Demo Application
│   ├── api/                                            # Node.js/Express backend API
│   ├── ui/                                             # Angular frontend UI
│   ├── deployment/                                     # Deployment scripts (Cloud Run)
│   ├── install.sh                                      # Installation script helper
│   ├── env.sh                                          # Environment setup helper
│   └── README.md                                       # README for the demo application
│
└── README.md                                           # This file
```


## Getting Started

### Prerequisites

* Google Cloud Project with billing enabled.
* An AlloyDB for PostgreSQL instance with the `google_ml_integration` and `pgvector` extensions enabled.
* [Google Cloud SDK (gcloud)](https://cloud.google.com/sdk/docs/install) installed and configured.
* Permissions to enable necessary Google Cloud APIs (e.g., Vertex AI, Cloud Run, Artifact Registry).
* Access to a Google Cloud environment where you can run Jupyter notebooks (e.g., Vertex AI Workbench).

### Option 1: Full Data Preparation

Use the `cymbal_shops_hybrid_search_alloydb_data_prep.ipynb` notebook for a detailed, step-by-step guide on:
* Setting up the AlloyDB tables.
* Generating text embeddings using Vertex AI.
* Generating sample product images (if applicable).
* Populating the database and configuring full-text search.

### Option 2: Quick Backend Setup

Use the `cymbal_shops_stylesearch_demo_shortcut.ipynb` notebook to quickly set up the AlloyDB backend using a pre-prepared dataset.

### Deploying the Demo Application

1.  Once the AlloyDB backend is prepared using one of the notebooks, navigate to the `demo_app/` directory.
2.  Follow the instructions in `demo_app/README.md` to deploy the backend API and frontend UI to Cloud Run.

## Contributing

Contributions are welcome!

## License

Please refer to the LICENSE file for details.

## Disclaimer

This is **NOT** an officially supported Google product.

This software is provided "as is", without warranty of any kind, expressed or implied, including but not limited to, the warranties of merchantability, fitness for a particular purpose, and/or infringement.

See LICENSE file for additional details.