import { Component, Input, ChangeDetectorRef, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { QueryResponse, Product } from '../../services/cymbalshops-api';
import { Observable } from 'rxjs';
import { MatCardModule } from '@angular/material/card';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatTableModule } from '@angular/material/table';
import { MatDividerModule } from '@angular/material/divider';
import { MatGridListModule } from '@angular/material/grid-list';
import { map } from 'rxjs/operators';
import { TextToHtmlPipe } from '../../common/text-to-html.pipe';
import { SqlStatementComponent } from '../../common/sql-statement/sql-statement.component';
import { RoleService } from '../../services/cymbalshops-api';

@Component({
  selector: 'app-product-results',
  standalone: true,
  imports: [
    CommonModule, 
    MatCardModule,
    MatExpansionModule,
    SqlStatementComponent,
    TextToHtmlPipe,
    MatTableModule,
    MatDividerModule,
    MatGridListModule,
  ],
  templateUrl: './product-results.component.html',
  styleUrl: './product-results.component.scss'
})

export class ProductResultsComponent implements OnInit {
  constructor (private cdr: ChangeDetectorRef,
    private RoleService: RoleService
  ) {}

  query?: string = undefined;
  data?: Product[] = undefined;
  generatedQuery?: string = undefined;
  errorDetail?: string = undefined;
  getSqlQuery?: string = undefined;

  currentRole: string | undefined;
  currentRoleId: number | null | undefined;
  currentRoleMap: Map<string, Array<number | null>> | undefined;
  subscriptionTier: number | null | undefined;
  enablePsv: boolean | undefined;

  ngOnInit(): void {
    console.log("Loading products component.")
    
    this.RoleService.role$.subscribe(roleMap => {
      if (roleMap) {
        const [role] = roleMap.keys(); // Get the role name from the Map
        this.currentRole = role;
        const roleArray = roleMap.get(role);
        this.currentRoleId = roleArray? roleArray[0] : undefined;
        this.subscriptionTier = roleArray? roleArray[1] : undefined;
      } else {
        this.currentRole = undefined;
      }
    });
  }
  
  @Input()
  set products(observable: Observable<QueryResponse<Product>> | undefined) {
    if (!observable) {
      // Clear data if observable is cleared
      this.data = undefined;
      this.query = undefined;
      this.generatedQuery = undefined;
      this.errorDetail = undefined;
      this.getSqlQuery = undefined;
      this.cdr.detectChanges();
      return;
    }
    
    observable.pipe(
      // Use the RxJS map operator to transform the response *before* subscription
      map(response => {
        // Check if data exists and has items
        if (response.data && response.data.length > 0) {

          // Process each product in the data array
          const modifiedData = response.data.map(product => {
            // Start with a shallow copy to avoid modifying the original object directly
            let modifiedProduct = { ...product };

            // --- 1. Modify productImageUri (existing logic) ---
            const stringToReplace = 'gs://genwealth-gen-vid';
            const replacementString = 'https://storage.googleapis.com/pr-public-demo-data/alloydb-retail-demo';
            if (modifiedProduct.productImageUri && typeof modifiedProduct.productImageUri === 'string') {
              modifiedProduct.productImageUri = modifiedProduct.productImageUri.replace(stringToReplace, replacementString);
            }

            // --- 2. Format rrf_score ---
            const decimalPlaces = 7;
            // Check if rrf_score exists and is a number
            if (modifiedProduct.rrfScore != null) {
              // This method keeps the type as number but might have floating point inaccuracies.
              const factor = Math.pow(10, decimalPlaces);
              modifiedProduct.rrfScore = Math.round(modifiedProduct.rrfScore * factor) / factor;

            }

            // Return the product object with potentially modified fields
            return modifiedProduct;
          });

          // Return a new response object containing the modified data array
          return { ...response, data: modifiedData };
        }

        // If there's no data, return the original response object
        return response;
      }) // End of map operator
    ).subscribe(response => { // Subscribe to the observable *after* the map transformation
      // Assign the already modified data to component properties
      this.query = response.query;
      this.data = response.data; // This 'data' now has the modified URIs
      this.generatedQuery = response.generatedQuery;
      this.errorDetail = response.errorDetail;
      this.getSqlQuery = response.getSqlQuery;

      // Trigger change detection *after* assignments
      this.cdr.detectChanges();

      // Keep your existing logic
      if (this.currentRole !== 'Admin' || this.searchType == 'FREEFORM') {
        this.enablePsv = true;
      } else {
        this.enablePsv = false;
      }
    });
  
  }


  @Input() searchType: string | undefined;

  public displaySearchQuery: string | undefined;
  private _searchQuery: string | undefined;
  @Input()
  set searchQuery(value: string | undefined) {

    this._searchQuery = value; // Store the original value

    // --- Apply .replace() logic here ---
    if (value) {

       this.displaySearchQuery = value.replace('gs://pr-public-demo-data', 'https://storage.googleapis.com/pr-public-demo-data');

    } else {
      this.displaySearchQuery = undefined; // Handle null/undefined input
    }
    console.log('Display search query set to:', this.displaySearchQuery);
  }

  getColumns(obj: any) {
    return Object.keys(obj);
  }

  getRows(obj: any) {
    return Object.values(obj);
  }
}
