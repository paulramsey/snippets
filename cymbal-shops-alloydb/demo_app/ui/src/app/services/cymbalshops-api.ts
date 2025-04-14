import { HttpClient, HttpParams } from '@angular/common/http';
import { Inject, Injectable } from '@angular/core';
import { Observable, BehaviorSubject, tap } from 'rxjs';
import { BASE_URL } from '../app.config';

export interface QueryResponse<T> {
    query?: string;
    data?: T[];
    generatedQuery?: string;
    errorDetail?: string;
    getSqlQuery?: string;
    searchType: string | undefined;
}

export interface Product {
    id?: number;
    cost?: number;
    category?: string;
    name?: string;
    brand?: string;
    retailPrice?: number;
    department?: string;
    sku?: string;
    distributionCenterId?: number;
    embedding?: string;
    embeddingModelVerion?: string;
    productDescription?: string;
    productDescriptionEmbedding?: string;
    productDescriptionEmbeddingModel?: string;
    productImageUri?: string;
    productImageEmbedding?: string;
    productImageEmbeddingModel?: string;
    ftsDocument?: string;
    sparseEmbedding?: string;
    sparseEmbeddingModel?: string;
    retrievalMethod?: string;
    rrfScore?: number;
    distance?: number;
}

export interface CymbalShopsService {
    searchProducts(term: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>>;
    fulltextSearchProducts(term: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>>;
    semanticSearchProducts(prompt: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>>;
    naturalSearchProducts(prompt: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>>;
    freeformSearchProducts(prompt: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>>;
    hybridSearchProducts(term: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>>;
    imageSearchProducts(searchUri: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>>;
}

@Injectable({
    providedIn: 'root'
})
export class CymbalShopsServiceClient implements CymbalShopsService {
    constructor(private http: HttpClient, @Inject(BASE_URL) private baseUrl: string) {}
    
    searchProducts(term: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>> {
        return this.http.get<QueryResponse<Product>>(`${this.baseUrl}/products/search`, {
            params: { term: term, currentRole: currentRole, currentRoleId: currentRoleId, subscriptionTier: subscriptionTier}
        });
    }

    fulltextSearchProducts(term: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>> {
        return this.http.get<QueryResponse<Product>>(`${this.baseUrl}/products/fulltext-search`, {
            params: { term: term, currentRole: currentRole, currentRoleId: currentRoleId, subscriptionTier: subscriptionTier}
        });
    }

    semanticSearchProducts(prompt: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>> {
        return this.http.get<QueryResponse<Product>>(`${this.baseUrl}/products/semantic-search`, {
            params: { prompt: prompt, currentRole: currentRole, currentRoleId: currentRoleId, subscriptionTier: subscriptionTier}
        });
    }

    naturalSearchProducts(prompt: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>> {
        return this.http.get<QueryResponse<Product>>(`${this.baseUrl}/products/natural-search`, {
            params: { prompt: prompt, currentRole: currentRole, currentRoleId: currentRoleId, subscriptionTier: subscriptionTier }
        });
    }

    freeformSearchProducts(prompt: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>> {
        return this.http.get<QueryResponse<Product>>(`${this.baseUrl}/products/freeform-search`, {
            params: { prompt: prompt, currentRole: currentRole, currentRoleId: currentRoleId, subscriptionTier: subscriptionTier }
        });
    }

    hybridSearchProducts(term: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>> {
        return this.http.get<QueryResponse<Product>>(`${this.baseUrl}/products/hybrid-search`, {
            params: { term: term, currentRole: currentRole, currentRoleId: currentRoleId, subscriptionTier: subscriptionTier}
        });
    }

    imageSearchProducts(searchUri: string, currentRole: string, currentRoleId: number, subscriptionTier: number): Observable<QueryResponse<Product>> {
        return this.http.get<QueryResponse<Product>>(`${this.baseUrl}/products/image-search`, {
            params: { searchUri: searchUri, currentRole: currentRole, currentRoleId: currentRoleId, subscriptionTier: subscriptionTier}
        });
    }
}

@Injectable({
    providedIn: 'root'
})
export class RoleService {
  private roleChangeSource = new BehaviorSubject<Map<string, Array<number | null>> 
 | undefined>(undefined);
  role$ = this.roleChangeSource.asObservable(); 

  updateRole(newRole: Map<string, Array<number | null>> | undefined) {
    this.roleChangeSource.next(newRole);
  }

  lookupRoleDetails(role: string): Map<string, Array<number | null>> | undefined {
    // Array should be formed as follows:
    // ["Role (Name)", [role_id, subscription_id]]
    const roleMap: Map<string, Array<number | null>> = new Map([
      ["Shopper (Paul Ramsey)", [1, 2]],
      ["Shopper (Evelyn Sterling)", [2, 2]],
      ["Shopper (Arthur Kensington)", [3, 2]],
      ["Shopper (Penelope Wainwright)", [4, 2]],
      ["Shopper (Sebastian Thorne)", [5, 2]],
      ["Admin", [0, 2]]
    ]);
  
    const id = roleMap.get(role);
  
    if (id !== undefined) {
      return new Map([[role, id]]); // Create a new Map with the role and its ID
    } else {
      return undefined;
    }
  }
}