import express from 'express';
import cors from 'cors';
import multer from 'multer';
import { join } from 'path';

import { Database, DatabasePsv } from './database';
import { Products } from './products';

//
// Create the express app
//
const app: express.Application = express();
const upload = multer();
const db: Database = new Database();
const dbPsv: DatabasePsv = new DatabasePsv();
const products = new Products(db, dbPsv);
const staticPath = join(__dirname, 'ui/dist/cymbal-shops-ui/browser');

//
// Use middleware
//
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(staticPath));

//
// Setup routes
//

/** Find products by search terms, 
 *  i.e. /products/search?terms=technology,high%20risk  */
app.get('/api/products/search', async (req: express.Request, res: express.Response) => {
  try 
  {
    const term: string = req.query.term as string;
    const currentRole: string = req.query.currentRole as string;
    const currentRoleId: number = req.query.currentRoleId as unknown as number;
    const subscriptionTier: number = req.query.subscriptionTier as unknown as number;

    const response = await products.search(term, currentRole, currentRoleId, subscriptionTier);
    res.json(response);
  }
  catch (err)
  {
    console.error('error occurred:', err);
    res.status(500).send(err);
  }
});

/** Find products by fulltext search, 
 *  i.e. /products/search?terms=technology,high%20risk  */
 app.get('/api/products/fulltext-search', async (req: express.Request, res: express.Response) => {
  try 
  {
    const term: string = req.query.term as string;
    const currentRole: string = req.query.currentRole as string;
    const currentRoleId: number = req.query.currentRoleId as unknown as number;
    const subscriptionTier: number = req.query.subscriptionTier as unknown as number;

    const response = await products.fulltextSearch(term, currentRole, currentRoleId, subscriptionTier);
    res.json(response);
  }
  catch (err)
  {
    console.error('error occurred:', err);
    res.status(500).send(err);
  }
});

/** Find products with natural language prompts 
 *  i.e. /products/semantic_search?prompt=hedge%20against%20%high%20inflation */
app.get('/api/products/semantic-search', async (req: express.Request, res: express.Response) => {
  try
  {
    const prompt: string = req.query.prompt as string;
    const currentRole: string = req.query.currentRole as string;
    const currentRoleId: number = req.query.currentRoleId as unknown as number;
    const subscriptionTier: number = req.query.subscriptionTier as unknown as number;

    const response = await products.semanticSearch(prompt, currentRole, currentRoleId, subscriptionTier);
    res.json(response);
  }
    catch (err)
    {
      console.error('error occurred:', err);
      res.status(500).send(err);
    }    
});

/** Find products a combination of techniques */
app.get('/api/products/hybrid-search', async (req: express.Request, res: express.Response) => {
  try 
  {
    const term: string = req.query.term as string;
    const currentRole: string = req.query.currentRole as string;
    const currentRoleId: number = req.query.currentRoleId as unknown as number;
    const subscriptionTier: number = req.query.subscriptionTier as unknown as number;

    const response = await products.hybridSearch(term, currentRole, currentRoleId, subscriptionTier);
    res.json(response);
  }
  catch (err)
  {
    console.error('error occurred:', err);
    res.status(500).send(err);
  }
});

/** Find products by image uri */
app.get('/api/products/image-search', async (req: express.Request, res: express.Response) => {
  try 
  {
    const searchUri: string = req.query.searchUri as string;
    const currentRole: string = req.query.currentRole as string;
    const currentRoleId: number = req.query.currentRoleId as unknown as number;
    const subscriptionTier: number = req.query.subscriptionTier as unknown as number;

    const response = await products.imageSearch(searchUri, currentRole, currentRoleId, subscriptionTier);
    res.json(response);
  }
  catch (err)
  {
    console.error('error occurred:', err);
    res.status(500).send(err);
  }
});

/** Find products with natural language prompts 
 *  i.e. /products/natural-search?prompt=hedge%20against%20%high%20inflation */
app.get('/api/products/natural-search', async (req: express.Request, res: express.Response) => {
  try
  {
    const prompt: string = req.query.prompt as string;
    const currentRole: string = req.query.currentRole as string;
    const currentRoleId: number = req.query.currentRoleId as unknown as number;
    const subscriptionTier: number = req.query.subscriptionTier as unknown as number;

    const response = await products.naturalSearch(prompt, currentRole, currentRoleId, subscriptionTier);
    res.json(response);
  }
    catch (err)
    {
      console.error('error occurred:', err);
      res.status(500).send(err);
    }    
});

/** Find products with arbitrary SQL (protected by PSV) 
*/
 app.get('/api/products/freeform-search', async (req: express.Request, res: express.Response) => {
  try
  {
    const prompt: string = req.query.prompt as string;
    const currentRole: string = req.query.currentRole as string;
    const currentRoleId: number = req.query.currentRoleId as unknown as number;
    const subscriptionTier: number = req.query.subscriptionTier as unknown as number;

    const response = await products.freeformSearch(prompt, currentRole, currentRoleId, subscriptionTier);
    res.json(response);
  }
    catch (err)
    {
      console.error('error occurred:', err);
      res.status(500).send(err);
    }    
});

/** Send any other request just to the static content
*/
app.get('*', (req, res) => {
  res.sendFile(join(staticPath, 'index.html'));
});

//
// Start the server
//
const port: number = parseInt(process.env.PORT ?? '8080');

app.listen(port, () => {
  console.log(`Cymbal Shops API: listening on port ${port}`);
});
