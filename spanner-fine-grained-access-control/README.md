# Spanner Fine-Grained Access Control (FGAC) Guide

This guide details how to enable and test Fine-Grained Access Control (FGAC) on a Google Cloud Spanner instance using `gcloud`. It also demonstrates how to update the IAM policy to add additional principals to a Database Role.

## Prerequisites

- Access to a Google Cloud Project with the Spanner API enabled.
- Permissions to manage IAM Service Accounts and Spanner Database IAM policies.
- `gcloud` CLI installed and authenticated.

## Setup Variables

```bash
export PROJECT_ID="your-project"
export INSTANCE_ID="your-instance"
export DATABASE_ID="your-database"
export SA_NAME="test-service-account"
export SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export DB_ROLE="SpannerDatabaseRole"

# Set default project
gcloud config set project $PROJECT_ID

# Navigate to the project directory
cd spanner-fine-grained-access-control
```

## Step 1: Create the IAM Service Account

In this context, we use a Service Account as the "IAM User" for testing purposes.

```bash
gcloud iam service-accounts create $SA_NAME \
    --display-name="Test Service Account for Spanner FGAC"
```

## Step 2: Configure IAM Roles for FGAC

We need to grant the Service Account two roles:
1.  `roles/spanner.fineGrainedAccessUser`: Allows the user to use fine-grained access.
2.  `roles/spanner.databaseRoleUser`: Allows the user to assume a specific Database Role.

### 1. Add `fineGrainedAccessUser` Role
Grant this on the Database (or Instance).

```bash
gcloud spanner databases add-iam-policy-binding $DATABASE_ID \
    --instance=$INSTANCE_ID \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/spanner.fineGrainedAccessUser" \
--condition=None
```

### 2. Add `databaseRoleUser` Role with Condition
Grant this on the Database, restricted to the specific role `SpannerDatabaseRole`.

```bash
gcloud spanner databases add-iam-policy-binding $DATABASE_ID \
    --instance=$INSTANCE_ID \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/spanner.databaseRoleUser" \
    --condition="expression=resource.name.endsWith('/databaseRoles/$DB_ROLE'),title=Access to $DB_ROLE"
```

## Step 3: Database Schema & Permissions

### 1. Create Test Table and Role
```bash
gcloud spanner databases ddl update $DATABASE_ID \
    --instance=$INSTANCE_ID \
    --ddl="CREATE TABLE TestTable (Id INT64, Data STRING(MAX)) PRIMARY KEY (Id); CREATE ROLE $DB_ROLE;"
```

### 2. Grant Permissions to the Role
Grant `READ` (SELECT), `INSERT`, and `UPDATE`, but **not** `DELETE`.
```bash
gcloud spanner databases ddl update $DATABASE_ID \
    --instance=$INSTANCE_ID \
    --ddl="GRANT SELECT, INSERT, UPDATE ON TABLE TestTable TO ROLE $DB_ROLE;"
```

## Step 4: Verify Permissions (User 1)

Test access by impersonating the service account.

### 1. Insert Data (Should Succeed)
```bash
gcloud spanner databases execute-sql $DATABASE_ID \
    --instance=$INSTANCE_ID \
    --impersonate-service-account=$SA_EMAIL \
    --database-role=$DB_ROLE \
    --sql="INSERT INTO TestTable (Id, Data) VALUES (1, 'Hello FGAC')"
```

### 2. Read Data (Should Succeed)
```bash
gcloud spanner databases execute-sql $DATABASE_ID \
    --instance=$INSTANCE_ID \
    --impersonate-service-account=$SA_EMAIL \
    --database-role=$DB_ROLE \
    --sql="SELECT * FROM TestTable"
```

### 3. Delete Data (Should Fail)
```bash
gcloud spanner databases execute-sql $DATABASE_ID \
    --instance=$INSTANCE_ID \
    --impersonate-service-account=$SA_EMAIL \
    --database-role=$DB_ROLE \
    --sql="DELETE FROM TestTable WHERE Id = 1"
# Expected output: Permission denied
```

## Step 5: Second User Scenario

Verify access by adding a second service account directly to the Database Role's IAM policy.

### 1. Setup Variables for User 2
```bash
export SA_NAME_2="test-service-account-2"
export SA_EMAIL_2="${SA_NAME_2}@${PROJECT_ID}.iam.gserviceaccount.com"
```

### 2. Create Service Account 2
```bash
gcloud iam service-accounts create $SA_NAME_2 --display-name="Test SA 2"
```

### 3. Grant `fineGrainedAccessUser` to SA 2
```bash
gcloud spanner databases add-iam-policy-binding $DATABASE_ID \
    --instance=$INSTANCE_ID \
    --member="serviceAccount:$SA_EMAIL_2" \
    --role="roles/spanner.fineGrainedAccessUser" \
    --condition=None
```

### 4. Get IAM Policy for Database Role

You will edit this policy to add the second service account to the `fineGrainedAccessUser` and `SpannerDatabaseRole` bindings in the next step.

```bash
gcloud spanner databases get-iam-policy $DATABASE_ID \
    --instance=$INSTANCE_ID \
    --format=json > ./policy.json
```

### 5. Update IAM Policy Document

Update the `policy.json` file to add the second service account to the `SpannerDatabaseRole` and `fineGrainedAccessUser` bindings. It should look similar to this:

```json
{
  "bindings": [
    {
      "condition": {
        "expression": "resource.name.endsWith('/databaseRoles/SpannerDatabaseRole')",
        "title": "Access to SpannerDatabaseRole"
      },
      "members": [
        "serviceAccount:test-service-account@your-project.iam.gserviceaccount.com",
        "serviceAccount:test-service-account-2@your-project.iam.gserviceaccount.com"
      ],
      "role": "roles/spanner.databaseRoleUser"
    },
    {
      "members": [
        "serviceAccount:test-service-account@your-project.iam.gserviceaccount.com",
        "serviceAccount:test-service-account-2@your-project.iam.gserviceaccount.com"
      ],
      "role": "roles/spanner.fineGrainedAccessUser"
    }
  ],
  "etag": "AwZHgYplstg=",
  "version": 3
}
```

### 6. Set IAM Policy for Database Role

Apply the updated `policy.json` to the database.

```bash
gcloud spanner databases set-iam-policy $DATABASE_ID \
    --instance=$INSTANCE_ID \
    ./policy.json
```

## Step 6: Verify Permissions (User 2)

### 1. Read Data (Should Succeed)
```bash
gcloud spanner databases execute-sql $DATABASE_ID \
    --instance=$INSTANCE_ID \
    --impersonate-service-account=$SA_EMAIL_2 \
    --database-role=$DB_ROLE \
    --sql="SELECT * FROM TestTable"
```

### 2. Delete Data (Should Fail)
```bash
gcloud spanner databases execute-sql $DATABASE_ID \
    --instance=$INSTANCE_ID \
    --impersonate-service-account=$SA_EMAIL_2 \
    --database-role=$DB_ROLE \
    --sql="DELETE FROM TestTable WHERE Id = 1"
# Expected output: Permission denied
```