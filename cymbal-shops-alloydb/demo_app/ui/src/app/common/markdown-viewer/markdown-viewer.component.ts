import { Component, Inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MAT_DIALOG_DATA } from '@angular/material/dialog';
import * as marked from 'marked'; 

@Component({
  selector: 'app-markdown-viewer',
  standalone: true,
  imports: [
    CommonModule
  ],
  templateUrl: './markdown-viewer.component.html',
  styleUrl: './markdown-viewer.component.scss'
})
export class MarkdownViewerComponent {
  parsedHtml: string | Promise<string> = '';

  constructor(@Inject(MAT_DIALOG_DATA) public data: { markdownSource: string | Promise<string> }) {
    fetch('assets/architecture.md')
      .then(response => response.text())
      .then(markdown => {
        console.log(JSON.stringify(markdown, null, 2));

        // Parse the markdown string into HTML
        this.parsedHtml = marked.parse(markdown); 
      })
      .catch(error => {
        console.error('Error fetching or parsing Markdown:', error);
        // Handle the error appropriately (e.g., display an error message)
      });
  }
}

