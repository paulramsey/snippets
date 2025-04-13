import { CommonModule } from '@angular/common';
import { Component, Input, OnChanges, SimpleChanges, AfterViewInit } from '@angular/core';
import { MatExpansionModule } from '@angular/material/expansion';

import { format } from 'sql-formatter';
import * as Prism from 'prismjs';

import 'prismjs/components/prism-sql.min.js'; 

@Component({
  selector: 'app-sql-statement',
  standalone: true,
  imports: [
    CommonModule,
    MatExpansionModule
  ],
  templateUrl: './sql-statement.component.html',
  styleUrl: './sql-statement.component.scss'
})
export class SqlStatementComponent implements OnChanges, AfterViewInit { // Implement OnChanges

  @Input() query?: string | undefined;
  formattedQuery?: string;

  ngOnChanges(changes: SimpleChanges): void {  // Use ngOnChanges
    if (changes['query']) {
      const newQuery = changes['query'].currentValue;
      if (newQuery) {
        this.query = format(newQuery, { language: 'postgresql' });
        Prism.highlightAll();
      } else {
        this.query = undefined;
      }
    }
  }

  ngAfterViewInit() { // Add ngAfterViewInit()
    Prism.highlightAll();
  }
}
