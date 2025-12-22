# Spanner Named Schema & Data Loader

This snippet demonstrates how to set up a Google Cloud Spanner environment with a **Named Schema**, a **Bit-Reversed Sequence**, and a **Java Data Loader** that populates data using the Mutation API.

## Overview

- **Schema**:
  - `ns`: A named schema namespace.
  - `my_seq`: A `bit_reversed_positive` sequence to ensure write distribution.
  - `ns.test_table`: A table using:
    - `id`: `STRING(36)` (UUID) as Primary Key (Best Practice).
    - `seq`: `INT64` column that captures the `BIT_REVERSE` value of the sequence (Human-readable-ish).
    - `last_updated`: `TIMESTAMP` with `allow_commit_timestamp=true`.

- **Data Loader**:
  - A Java application using `google-cloud-spanner` library.
  - Inserts 100 records using **Mutations** (not DML).
  - Uses `Value.COMMIT_TIMESTAMP` for the timestamp column.

## Prerequisites

- **Google Cloud SDK (`gcloud`)** authenticated and configured with your project.
- **Java 21+** (Verified with JDK 25).
- **Maven** (3.9.9+).

## Infrastructure Setup

1. **Enable APIs**:
   ```bash
   gcloud services enable spanner.googleapis.com
   ```

2. **Create Instance & Database**:
   ```bash
   gcloud spanner instances create dev-instance --config=regional-us-central1 --description="Dev Instance" --nodes=1
   gcloud spanner databases create dev-db --instance=dev-instance
   ```

3. **Apply Schema**:
   The schema includes the named schema `ns`, sequence `my_seq`, and table `ns.test_table`.
   ```bash
   gcloud spanner databases ddl update dev-db --instance=dev-instance --ddl-file=schema.ddl
   ```

## Running the Data Loader

The data loader is a Maven project located in `spanner-loader/`.

1. **Navigate to the loader directory**:
   ```bash
   cd spanner-loader
   ```

2. **Run the application**:
   ```bash
   mvn clean compile exec:java -Dexec.mainClass="com.example.spanner.SpannerPopulate" -Dexec.cleanupDaemonThreads=false
   ```

   **Expected Output**:
   ```
   Generating mutations...
   Writing 100 mutations...
   Written 100 records at <Timestamp>
   ```

## Verification

You can verify the data in Spanner using `gcloud` or the Console:

```bash
gcloud spanner databases execute-sql dev-db --instance=dev-instance \
  --sql="SELECT * FROM ns.test_table LIMIT 5"
```
