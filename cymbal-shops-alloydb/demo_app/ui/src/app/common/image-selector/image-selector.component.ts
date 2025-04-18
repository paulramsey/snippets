import { Component, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common'; // Import CommonModule for *ngFor, [ngClass] etc.
import { MatCardModule } from '@angular/material/card';

// Interface for clarity (optional but recommended)
interface SelectableImage {
  id: number; // Or any unique identifier
  uri: string;
  url: string;
  alt: string;
}

@Component({
  selector: 'app-image-selector',
  standalone: true,
  imports: [
    CommonModule, // <-- Import here for standalone component
    MatCardModule, 
  ],
  templateUrl: './image-selector.component.html',
  styleUrls: ['./image-selector.component.scss']
})
export class ImageSelectorComponent {

  images: SelectableImage[] = [
    { id: 1, uri: 'gs://pr-public-demo-data/alloydb-retail-demo/user_photos/1.png', url: 'https://storage.googleapis.com/pr-public-demo-data/alloydb-retail-demo/user_photos/1.png', alt: 'Blue Jacket' },
    { id: 2, uri: 'gs://pr-public-demo-data/alloydb-retail-demo/user_photos/2.png', url: 'https://storage.googleapis.com/pr-public-demo-data/alloydb-retail-demo/user_photos/2.png', alt: 'Brown Jacket' },
    { id: 3, uri: 'gs://pr-public-demo-data/alloydb-retail-demo/user_photos/3.png', url: 'https://storage.googleapis.com/pr-public-demo-data/alloydb-retail-demo/user_photos/3.png', alt: 'Black Coat' },
    { id: 4, uri: 'gs://pr-public-demo-data/alloydb-retail-demo/user_photos/4.png', url: 'https://storage.googleapis.com/pr-public-demo-data/alloydb-retail-demo/user_photos/4.png', alt: 'Gray Puffer Jacket' },
    { id: 5, uri: 'gs://pr-public-demo-data/alloydb-retail-demo/user_photos/5.png', url: 'https://storage.googleapis.com/pr-public-demo-data/alloydb-retail-demo/user_photos/5.png', alt: 'Noogler Hat' },
  ];

  // Variable to store the URI of the selected image
  selectedImageUri: string | null = null; // Initialize to null or undefined

  // Define the Output propert
  @Output() imageSelected = new EventEmitter<string>(); // Will emit the selected string URI

  // Method called when an image container is clicked
  selectImage(imageUri: string): void {
    this.selectedImageUri = imageUri; // Update internal state (for highlighting)

    // Emit the selected URI to the parent component
    this.imageSelected.emit(this.selectedImageUri);
  }
}
