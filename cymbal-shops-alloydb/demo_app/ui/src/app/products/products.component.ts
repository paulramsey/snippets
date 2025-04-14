import { Component, ChangeDetectorRef, OnInit, ApplicationRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { CymbalShopsServiceClient, Product, QueryResponse } from '../services/cymbalshops-api';
import { Observable, catchError, finalize } from 'rxjs';

import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatRadioModule } from '@angular/material/radio';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { ProductResultsComponent } from './results/product-results.component';
import { SnackBarErrorComponent } from '../common/SnackBarErrorComponent';
import { ActivatedRoute } from '@angular/router';

import { RoleService } from '../services/cymbalshops-api';

import { ImageSelectorComponent } from '../common/image-selector/image-selector.component';


export enum SearchType {
  TRADITIONAL_SQL = 'traditionalSql',
  TEXT_EMBEDDINGS = 'textEmbeddings',
  FULLTEXT = 'fulltext',
  NATURAL = 'natural',
  FREEFORM = 'freeform',
  HYBRID = 'hybrid',
  IMAGE = 'image',
}

@Component({
  selector: 'app-products',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    FormsModule,
    MatInputModule,
    MatCardModule,
    MatRadioModule,
    MatIconModule,
    MatTooltipModule,
    ProductResultsComponent,
    MatProgressSpinnerModule,
    ImageSelectorComponent,
  ],
  templateUrl: './products.component.html',
  styleUrl: './products.component.scss'
})
export class ProductsComponent implements OnInit {
  constructor(
    private CymbalShopsClient: CymbalShopsServiceClient,
    private error: SnackBarErrorComponent,
    private RoleService: RoleService,
    private ApplicationRef: ApplicationRef) {}

  currentRole: string | undefined;
  currentRoleId: number | null | undefined;
  currentRoleMap: Map<string, Array<number | null>> | undefined;
  subscriptionTier: number | null | undefined;
  validRole: boolean | undefined;

  searchTypes = SearchType; // Make enum accessible in template
  productSearch: string = '';
  searchType: string = SearchType.TRADITIONAL_SQL; // Default search type
  loading: boolean = false;
  products?: Observable<QueryResponse<Product>> = undefined;

  SEARCH_PLACEHOLDER = "What can we help you find?";
  SEARCH_PLACEHOLDER_IMAGE = "Enter a gs:// URI...";
  BUTTON_TEXT = "Find";
  LOADING_BUTTON_TEXT = "Generating SQL";
  
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

      if (this.currentRole == 'Admin' || this.currentRole?.includes("Subscriber")) {
        this.validRole = true;
      } else {
        this.validRole = false;
      }
    });
    
  }

  findProducts()  {
    this.loading = true;
    switch (this.searchType) {
      case SearchType.TRADITIONAL_SQL:
        this.products =
         this.CymbalShopsClient.searchProducts(this.productSearch, this.currentRole!, this.currentRoleId!, this.subscriptionTier!).pipe(
            catchError((err: any) => {
              this.error.showError('Unable to search products', err);
              return [];
            }),
            finalize(() => {
              this.loading = false;
              this.ApplicationRef.tick();
            })
          );
        break;
      case SearchType.TEXT_EMBEDDINGS:
        this.products =
          this.CymbalShopsClient.semanticSearchProducts(this.productSearch, this.currentRole!, this.currentRoleId!, this.subscriptionTier!).pipe(
            catchError((err: any) => {
              this.error.showError('Unable to search products', err);
              return [];
            }),
            finalize(() => {
              this.loading = false;
              this.ApplicationRef.tick();
            })
          );
        break;
      case SearchType.FULLTEXT:
          this.products =
            this.CymbalShopsClient.fulltextSearchProducts(this.productSearch, this.currentRole!, this.currentRoleId!, this.subscriptionTier!).pipe(
              catchError((err: any) => {
                this.error.showError('Unable to search products', err);
                return [];
              }),
              finalize(() => {
                this.loading = false;
                this.ApplicationRef.tick();
              })
            );
          break;
      case SearchType.NATURAL:
        this.products =
          this.CymbalShopsClient.naturalSearchProducts(this.productSearch, this.currentRole!, this.currentRoleId!, this.subscriptionTier!).pipe(
            catchError((err: any) => {
              this.error.showError(JSON.stringify(err), err);
              return [];
            }),
            finalize(() => {
              this.loading = false;
              this.ApplicationRef.tick();
            })
          );
        break;
      case SearchType.FREEFORM:
        this.products =
          this.CymbalShopsClient.freeformSearchProducts(this.productSearch, this.currentRole!, this.currentRoleId!, this.subscriptionTier!).pipe(
            catchError((err: any) => {
              this.error.showError(JSON.stringify(err), err);
              return [];
            }),
            finalize(() => {
              this.loading = false;
              this.ApplicationRef.tick();
            })
          );
        break;
      case SearchType.HYBRID:
        this.products =
          this.CymbalShopsClient.hybridSearchProducts(this.productSearch, this.currentRole!, this.currentRoleId!, this.subscriptionTier!).pipe(
            catchError((err: any) => {
              this.error.showError(JSON.stringify(err), err);
              return [];
            }),
            finalize(() => {
              this.loading = false;
              this.ApplicationRef.tick();
            })
          );
        break;
      case SearchType.IMAGE:
        this.products =
          this.CymbalShopsClient.imageSearchProducts(this.productSearch, this.currentRole!, this.currentRoleId!, this.subscriptionTier!).pipe(
            catchError((err: any) => {
              this.error.showError(JSON.stringify(err), err);
              return [];
            }),
            finalize(() => {
              this.loading = false;
              this.ApplicationRef.tick();
            })
          );
        break;
      default:
        break;
    }
  }

  onImageSelectedFromChild(selectedUri: string): void {
    // Update the parent component's property
    this.productSearch = selectedUri;

    // Optional: Automatically trigger search when an image is selected
    if (this.searchType === SearchType.IMAGE) {
       this.findProducts();
    }
  }


  getSuggestion() {
    switch (this.searchType) {
      case SearchType.TRADITIONAL_SQL:
        return "Black belt";
      case SearchType.FULLTEXT:
        return "Black belt";
      case SearchType.TEXT_EMBEDDINGS:
        return "Coach purse";
      case SearchType.HYBRID:
        return "Coach purse";
      case SearchType.IMAGE:
        return "gs://pr-public-demo-data/alloydb-retail-demo/user_photos/1.png";
      case SearchType.NATURAL:
        return "What are some popular purses my wife might like?";
      case SearchType.FREEFORM:
        return "SELECT * FROM products LIMIT 5;";
      default:
        return '';
    }
  }

}
