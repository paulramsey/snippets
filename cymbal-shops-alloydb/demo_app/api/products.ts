import { Database, DatabasePsv, camelCaseRows, safeString } from './database';

export class Products {
    constructor(private db: Database,
        private dbPsv: DatabasePsv
    ) { }

    private async executeQuery(query: string, currentRole: string, currentRoleId: number, subscriptionTier: number, searchType: string, generatedQuery: string = "", getSqlQuery: string = ""): Promise<{ data: any[], query: string, generatedQuery?: string, getSqlQuery?: string, errorDetail?: string , searchType?: string}> {
        let flattenResults = false;
        let resultRows: any[] = [];  

        if (currentRole !== 'Admin' || searchType == 'FREEFORM') {
            flattenResults = true;
            let psv_query = query.replace("FROM investments", "FROM psv_investments");
            psv_query = psv_query.replace("FROM user_profiles", "FROM psv_user_profiles");
            psv_query = psv_query.replace(/'/g, "''");

            query = `SELECT * FROM
            parameterized_views.execute_parameterized_query(
                query => '${psv_query}',
                param_names => ARRAY ['advisor_id', 'subscription_tier'],
                param_values => ARRAY ['${String(currentRoleId)}', '${String(subscriptionTier)}']
            )`;
        }

        try {
            let rows;
            if (currentRole === 'Admin') {
                rows = await this.db.query(query);
            } else {
                rows = await this.dbPsv.query(query); // Use dbPsv for PSV queries
            }

            if (flattenResults) {
                for (let row of rows) {
                    resultRows.push(row['json_results']);
                }
            }

            return { 
                data: camelCaseRows(flattenResults ? resultRows : rows), 
                query: query, 
                generatedQuery: generatedQuery, 
                getSqlQuery: getSqlQuery 
            };
        } catch (error) {
            const errorDetail = `Error executing query: ${query}.\nError: ${(error as Error)?.message}`;
            console.error(errorDetail);
            return { data: [], query: query, generatedQuery: generatedQuery, getSqlQuery: getSqlQuery, errorDetail: errorDetail }; 
        }
    }

    async search(searchTerm: string, currentRole: string, currentRoleId: number, subscriptionTier: number) {
        let query;
        let searchType = 'TRADITIONAL_SQL';
        try {
            console.log('using searchTerm', searchTerm, ' with role: ', currentRole);

            let formattedSearchTerm = searchTerm.replace(/\s+/g, ' ').split(' ').join('%')
            query = `SELECT
                        name,
                        product_image_uri,
                        brand,
                        product_description,
                        category,
                        department,
                        cost,
                        retail_price::MONEY,
                        sku,
                        'SQL' AS retrieval_method
                        FROM products
                        WHERE name ILIKE '%${safeString(formattedSearchTerm) ?? ''}%'
                        OR sku ILIKE '%${safeString(formattedSearchTerm) ?? ''}%'
                        OR category ILIKE '%${safeString(formattedSearchTerm) ?? ''}%'
                        OR brand ILIKE '%${safeString(formattedSearchTerm) ?? ''}%'
                        OR department ILIKE '%${safeString(formattedSearchTerm) ?? ''}%'
                        OR product_description ILIKE '%${safeString(formattedSearchTerm) ?? ''}%'
                        ORDER BY name
                        LIMIT 12;`;

            return this.executeQuery(query, currentRole, currentRoleId, subscriptionTier, searchType);
        } catch (error) {
            const errorDetail = `search errored with query: ${query}.\nError: ${(error as Error)?.message}`;
            console.error(errorDetail);
            return { data: [], query: query, errorDetail: errorDetail, searchType: searchType };
        }
    }

    async fulltextSearch(searchTerm: string, currentRole: string, currentRoleId: number, subscriptionTier: number) {
        let query;
        let searchType = 'FULLTEXT';
        try {
            console.log('using searchTerm', searchTerm, ' with role: ', currentRole);
            query = `
                SELECT
                    ts_rank(fts_document, websearch_to_tsquery('english', '${safeString(searchTerm) ?? ''}')) AS fts_rank_score,
                    name,
                    product_image_uri,
                    brand,
                    product_description,
                    category,
                    department,
                    cost,
                    retail_price::MONEY,
                    sku,
                    'FTS' AS retrieval_method
                FROM products
                WHERE fts_document @@ websearch_to_tsquery('english', '${safeString(searchTerm) ?? ''}')
                ORDER BY fts_rank_score DESC
                LIMIT 12;`;

            return this.executeQuery(query, currentRole, currentRoleId, subscriptionTier, searchType);
        } catch (error) {
            const errorDetail = `fulltextSearch errored with query: ${query}.\nError: ${(error as Error)?.message}`;
            console.error(errorDetail);
            return { data: [], query: query, errorDetail: errorDetail, searchType: searchType };
        }
    }

    async semanticSearch(prompt: string, currentRole: string, currentRoleId: number, subscriptionTier: number) {
        let query;
        let searchType = 'SEMANTIC';
        try {
            query = `
            SELECT embedding <=> embedding('text-embedding-005', '${safeString(prompt)}')::vector AS distance,
                name,
                product_image_uri,
                brand,
                product_description,
                category,
                department,
                cost,
                retail_price::MONEY,
                sku,
                'VECTOR' AS retrieval_method
            FROM products
            ORDER BY distance
            LIMIT 12`;

        return this.executeQuery(query, currentRole, currentRoleId, subscriptionTier, searchType);
        } catch (error) {
            const errorDetail = `semanticSearch errored with query: ${query}.\nError: ${(error as Error)?.message}`;
            console.error(errorDetail);
            return { data: [], query: query, errorDetail: errorDetail, searchType: searchType };
        }
    }
    
    async hybridSearch(searchTerm: string, currentRole: string, currentRoleId: number, subscriptionTier: number) {
        let query;
        let searchType = 'HYBRID';
        try {
            
            let ftsSearchTerm = searchTerm
            let vectorSearchTerm = searchTerm.replace(/\s+/g, ' ').replace(/'+/g, '').replace(/"+/g, '').replace(/-+/g, '')
            let sqlSearchTerm = vectorSearchTerm.split(' ').join('%')
            
            query = `WITH trad_sql AS (
                SELECT
                RANK () OVER (ORDER BY name) AS trad_sql_rank,
                id,
                name,
                product_image_uri,
                brand,
                product_description,
                category,
                department,
                cost,
                retail_price,
                sku,
                'SQL' AS retrieval_method
                FROM products
                WHERE sku = '${safeString(sqlSearchTerm)}'
                ORDER BY name
                LIMIT 40
            ), fts_search AS (
            SELECT
                ts_rank(fts_document, websearch_to_tsquery('english', '${safeString(ftsSearchTerm)}')) AS fts_rank_score,
                RANK () OVER (ORDER BY ts_rank(fts_document, websearch_to_tsquery('english', '${safeString(ftsSearchTerm)}')) DESC) as fts_rank,
                id,
                name,
                product_image_uri,
                brand,
                product_description,
                category,
                department,
                cost,
                retail_price,
                sku,
                'FTS' AS retrieval_method
            FROM products
            WHERE fts_document @@ websearch_to_tsquery('english', '${safeString(ftsSearchTerm)}')
            ORDER BY fts_rank_score DESC
            LIMIT 40
            ), vector_search AS (
            SELECT embedding <=> embedding('text-embedding-005', '${safeString(vectorSearchTerm)}')::vector AS distance,
                RANK () OVER (ORDER BY embedding <=> embedding('text-embedding-005', '${safeString(vectorSearchTerm)}')::vector) AS vector_rank,
                id,
                name,
                product_image_uri,
                brand,
                product_description,
                category,
                department,
                cost,
                retail_price,
                sku,
                'VECTOR' AS retrieval_method
            FROM products
            ORDER BY distance
            LIMIT 40
            ) SELECT
                COALESCE(vector_search.id, fts_search.id, trad_sql.id) AS id,
                (
                COALESCE( (1.0 / (60 + vector_search.vector_rank)), 0.0 ) +
                COALESCE( (1.0 / (60 + fts_search.fts_rank)), 0.0 ) +
                COALESCE( (1.0 / (60 + trad_sql.trad_sql_rank)), 0.0 )
                ) AS rrf_score,
                CONCAT_WS(
                    '+',
                    CASE WHEN vector_search.vector_rank IS NOT NULL THEN 'VECTOR' ELSE NULL END,
                    CASE WHEN fts_search.fts_rank IS NOT NULL THEN 'FTS' ELSE NULL END,
                    CASE WHEN trad_sql.trad_sql_rank IS NOT NULL THEN 'SQL' ELSE NULL END
                ) AS retrieval_method,
                COALESCE(vector_search.id, fts_search.id, trad_sql.id) AS id,
                COALESCE(vector_search.name, fts_search.name, trad_sql.name) AS name,
                COALESCE(vector_search.product_image_uri, fts_search.product_image_uri, trad_sql.product_image_uri) AS product_image_uri,
                COALESCE(vector_search.brand, fts_search.brand, trad_sql.brand) AS brand,
                COALESCE(vector_search.product_description, fts_search.product_description, trad_sql.product_description) AS product_description,
                COALESCE(vector_search.category, fts_search.category, trad_sql.category) AS category,
                COALESCE(vector_search.department, fts_search.department, trad_sql.department) AS department,
                COALESCE(vector_search.cost, fts_search.cost, trad_sql.cost) AS cost,
                COALESCE(vector_search.retail_price, fts_search.retail_price, trad_sql.retail_price)::MONEY AS retail_price,
                COALESCE(vector_search.sku, fts_search.sku, trad_sql.sku) AS sku
            FROM vector_search
            FULL OUTER JOIN fts_search ON vector_search.id = fts_search.id
            FULL OUTER JOIN trad_sql ON COALESCE(vector_search.id, fts_search.id) = trad_sql.id
            ORDER BY rrf_score DESC
            LIMIT 20`;

        return this.executeQuery(query, currentRole, currentRoleId, subscriptionTier, searchType);
        } catch (error) {
            const errorDetail = `hybridSearch errored with query: ${query}.\nError: ${(error as Error)?.message}`;
            console.error(errorDetail);
            return { data: [], query: query, errorDetail: errorDetail, searchType: searchType };
        }
    }

    async imageSearch(searchUri: string, currentRole: string, currentRoleId: number, subscriptionTier: number) {
        let query;
        let searchType = 'IMAGE';
        try {
            console.log('using searchUri', searchUri, ' with role: ', currentRole);
            query = `
                WITH image_embedding AS (
                SELECT ai.image_embedding(
                    model_id => 'multimodalembedding@001',
                    image => '${safeString(searchUri) ?? ''}',
                    mimetype => 'image/png')::vector AS embedding
                ), multimodal_vector_search AS (
                SELECT product_image_embedding <=> image_embedding.embedding AS distance,
                    name,
                    product_image_uri,
                    brand,
                    product_description,
                    category,
                    department,
                    cost,
                    retail_price::MONEY,
                    sku
                FROM products, image_embedding
                ORDER BY distance
                LIMIT 24
                ) SELECT RANK () OVER (ORDER BY distance) AS vector_rank, *
                FROM multimodal_vector_search;`;

            return this.executeQuery(query, currentRole, currentRoleId, subscriptionTier, searchType);
        } catch (error) {
            const errorDetail = `imageSearch errored with query: ${query}.\nError: ${(error as Error)?.message}`;
            console.error(errorDetail);
            return { data: [], query: query, errorDetail: errorDetail, searchType: searchType };
        }
    }


    async naturalSearch(prompt: string, currentRole: string, currentRoleId: number, subscriptionTier: number) {
        let query, generatedQuery, getSqlQuery;
        let searchType = 'NATURAL';
        try {
            const nlConfig = currentRole === 'Admin' ? 'ragdemos' : 'psv';

            getSqlQuery = `SELECT alloydb_ai_nl.get_sql(
                nl_config_id => '${nlConfig}',
                nl_question => '${safeString(prompt)}'
            )  ->> 'sql' AS generated_sql`;

            let generateSql;
            if (currentRole === 'Admin') {
                generateSql = await this.db.query(getSqlQuery);
            } else {
                generateSql = await this.dbPsv.query(getSqlQuery);
            }

            generatedQuery = generateSql[0].generated_sql;

            // Now you can use executeQuery with the generated SQL
            const result = await this.executeQuery(generatedQuery, currentRole, currentRoleId, subscriptionTier, searchType, generatedQuery, getSqlQuery);
            //result.generatedQuery = generatedQuery; // Add generatedQuery to the result
            return result; 

        } catch (error) {
            const errorDetail = `naturalSearch errored with query: ${query} and \ngeneratedQuery: ${generatedQuery}.\nError: ${(error as Error)?.message}`;
            console.error(errorDetail);
            return { query: query, generatedQuery: generatedQuery, errorDetail: errorDetail, getSqlQuery: getSqlQuery, searchType: searchType };
        }
    }

    async freeformSearch(prompt: string, currentRole: string, currentRoleId: number, subscriptionTier: number) {
        let query;
        let searchType = 'FREEFORM';
        try {
            query = prompt;

            return this.executeQuery(query, currentRole, currentRoleId, subscriptionTier, searchType);
        } catch (error) {
            const errorDetail = `freeformSearch errored with query: ${query}.\nError: ${(error as Error)?.message}`;
            console.error(errorDetail);
            return { data: [], query: query, errorDetail: errorDetail, searchType: searchType };
        }
    }
}
