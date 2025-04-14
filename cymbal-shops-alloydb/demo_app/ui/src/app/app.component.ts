import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterOutlet } from '@angular/router';
import { RouterModule } from '@angular/router';
import { BreakpointObserver, Breakpoints} from '@angular/cdk/layout';

import { MatButtonModule } from '@angular/material/button';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatIconModule } from '@angular/material/icon';

import { ProductsComponent } from './products/products.component';
import { SnackBarErrorComponent } from './common/SnackBarErrorComponent';

import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDividerModule } from '@angular/material/divider';

import { MatMenuModule } from '@angular/material/menu';

import { RoleService } from './services/cymbalshops-api';

import { MatDialog, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MarkdownViewerComponent } from './common/markdown-viewer/markdown-viewer.component';
import { HttpClient } from '@angular/common/http';

import { ArchitectureComponent } from './architecture/architecture.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    CommonModule, 
    RouterOutlet, 
    RouterModule,
    MatButtonModule,
    MatToolbarModule,
    MatIconModule,
    ProductsComponent,
    MatButtonToggleModule, 
    MatCheckboxModule,
    MatDividerModule,
    MatMenuModule,
    MarkdownViewerComponent,
    ArchitectureComponent,
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
  providers: [SnackBarErrorComponent]
})
export class AppComponent implements OnInit {
  constructor(
    private breakpointObserver: BreakpointObserver, 
    private RoleService: RoleService,
    public dialog: MatDialog,
    private http: HttpClient) {}

  isSmallScreen: boolean = false;

  currentRole: string | undefined;
  currentRoleId: number | null | undefined;
  subscriptionTier: number | null | undefined;
  currentRoleMap: Map<string, Array<number | null>> | undefined;

  markdownContent = '';

  ngOnInit() { 
    this.breakpointObserver
      .observe([Breakpoints.Handset])
      .subscribe( _ => this.isSmallScreen = this.breakpointObserver.isMatched(Breakpoints.Handset) )
    
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

    this.currentRoleMap = this.RoleService.lookupRoleDetails('Admin')
    this.RoleService.updateRole(this.currentRoleMap);
  }

  

  select(pText :string)
  {
    this.currentRole = pText
    this.currentRoleMap = this.RoleService.lookupRoleDetails(this.currentRole)
    this.RoleService.updateRole(this.currentRoleMap);
  }

  openArchitectureDialog() {
    this.dialog.open(ArchitectureComponent, { 
      height: '90%',
      width: '90%'
    });
  }

}
