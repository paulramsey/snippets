# CymbalShops StyleSearch Demo App

## Requirements
- Node 20+
- Angular 17+
- Deploy AlloyDB with schema & sample data using the [accompanying notebook](../cymbal_shops_hybrid_search_alloydb_data_prep.ipynb).

## Architecture

### Backend
The backend is hosted in GCP on AlloyDB which makes calls direct to VertexAI through the database engine. 

### Middle Tier
The middle tier is written in TypeScript and hosted with `express`: 

```javascript
import express from 'express';
...
const app: express.Application = express();
```

There are a simple set of REST apis hosted at `/api/*` that connect to AlloyDB via the `Database.ts` class.  

```javascript
// Routes for the backend
app.get('/api/products/search', async (req: express.Request, res: express.Response) => {
  ...
}
```

### Frontend
 
The frontend application is Angular Material using TypeScript, which is built and statically served from the root `/` by express as well:

```javascript
// Serve the frontend
app.use(express.static(staticPath));

```

## Run the application
```bash
# Clone this repository
git clone http://github.com/paulramsey/snippets.git
cd snippets

# Run: 
cd cymbal-shops-alloydb/demo_app/api/
npm install
npm start

# Open and another shell and run:
cd cymbal-shops-alloydb/demo_app/ui/
npm install
npm start
```

## Deploying the application

> NOTE: This works best from CloudShell. 

1. Clone this repository:
```bash
git clone http://github.com/paulramsey/snippets.git
cd snippets
```

2. Authenticate to Google Cloud
```bash
gcloud auth login
gcloud auth application-default login
```

3. Set your project context
```bash
gcloud config set project <PROJECT_ID>
gcloud config list project
```

4. **IMPORTANT** Set values in the `./env.sh` file for your environment, then run:
```bash
cd cymbal-shops-alloydb/demo_app
source ./env.sh # Enter your AlloyDB password when prompted
source ./install.sh
```

5. Deploy the application:
```bash
source ./install.sh
```

## Request Flow

### Example Flow for Product Search Request

High level flow for a product search request:
products.component.html
products.component.ts
cymbalshops-api.ts
index.ts
products.ts
database.ts


### Detailed Flow for Traditional SQL Search

UI:
products.component.html -> productSearch (enter text)
products.component.ts -> this.productSearch
products.component.html -> findProducts()
products.component.ts -> findProducts() -> Check this.searchType()
products.component.ts -> this.CymbalShopsClient.searchProducts() -> CymbalShopsClient -> CymbalShopsServiceClient import from cymbalshops-api
cymbalshops-api.ts -> CymbalShopsServiceClient -> searchProducts() -> this.http.get(/products/search) API

API:
index.ts -> app.get('/api/products/search') (implicit conversion from params to req.query)
index.ts -> products.search() -> Products import from products.ts
products.ts -> Products -> async search() <- This is where the query is actually written
products.ts -> this.executeQuery -> async executeQuery -> Check role -> this.db.query() or this.dbPsv.query() -> Database -> import from database.ts
database.ts -> async query() -> this.pool.connect() -> client.query() -> pg library